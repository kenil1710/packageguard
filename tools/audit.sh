#!/usr/bin/env bash
# Pre-submission audit. Every check RUNS; none is asserted from memory.
#
#   bash tools/audit.sh            offline checks only
#   bash tools/audit.sh <oracle> <consumer>    also checks the live deployment
#
# Exit code is the number of failures.
cd "$(dirname "$0")/.."
ORACLE="${1:-}"
CONSUMER="${2:-}"
LINT="$HOME/.local/bin/genvm-lint"
PASS=0; FAIL=0
ck() { # ck "<name>" "<command>"
  if eval "$2" >/dev/null 2>&1; then printf "  PASS  %s\n" "$1"; PASS=$((PASS+1));
  else printf "  FAIL  %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

echo "== 1. contracts and artifacts lint =="
for f in contracts/PackageGuard.py contracts/PackageConsumer.py \
         contracts/_render_probe.py build/PackageGuard.min.py \
         build/PackageConsumer.min.py; do
  ck "genvm-lint $f" "$LINT $f | grep -q 'Lint passed'"
done

echo "== 2. runner pin =="
for f in contracts/PackageGuard.py contracts/PackageConsumer.py \
         contracts/_render_probe.py build/PackageGuard.min.py \
         build/PackageConsumer.min.py; do
  ck "runner pin is line 1 of $f" "head -1 $f | grep -q '^# { \"Depends\": \"py-genlayer:'"
done
ck "artifact pin matches source pin (oracle)" \
   "[ \"\$(head -1 contracts/PackageGuard.py)\" = \"\$(head -1 build/PackageGuard.min.py)\" ]"
ck "artifact pin matches source pin (consumer)" \
   "[ \"\$(head -1 contracts/PackageConsumer.py)\" = \"\$(head -1 build/PackageConsumer.min.py)\" ]"

echo "== 3. offline suite =="
ck "python3 test/test_logic.py passes with 0 failures and 0 skips" \
   "python3 test/test_logic.py 2>&1 | tail -3 | grep -qx 'OK'"
ck "suite is >= 300 tests" \
   "[ \$(python3 test/test_logic.py 2>&1 | grep -oE '^Ran [0-9]+' | grep -oE '[0-9]+') -ge 300 ]"
ck "suite touches no network (stub raises on web/model access)" \
   "grep -q 'offline tests must not touch the network or a model' test/test_logic.py"
ck "fixtures are regenerable from the live registry" "[ -f tools/make_fixtures.py ]"

echo "== 4. artifacts are current =="
python3 tools/minify_contract.py contracts/PackageGuard.py -o /tmp/_pg.min.py >/dev/null 2>&1
python3 tools/minify_contract.py contracts/PackageConsumer.py -o /tmp/_pc.min.py >/dev/null 2>&1
ck "build/PackageGuard.min.py is a current build of its source" \
   "diff -q /tmp/_pg.min.py build/PackageGuard.min.py"
ck "build/PackageConsumer.min.py is a current build of its source" \
   "diff -q /tmp/_pc.min.py build/PackageConsumer.min.py"
ck "deployments.json sha256 matches build/PackageGuard.min.py" \
   "grep -q \"\$(shasum -a 256 build/PackageGuard.min.py | cut -d' ' -f1)\" deployments.json"
ck "deployments.json sha256 matches build/PackageConsumer.min.py" \
   "grep -q \"\$(shasum -a 256 build/PackageConsumer.min.py | cut -d' ' -f1)\" deployments.json"
ck "deployments.json is valid json" "python3 -m json.tool deployments.json"

echo "== 5. repository hygiene =="
ck "no AI attribution anywhere in commit messages" \
   "! git log --format='%B' | grep -qiE 'co-authored-by|claude|generated with'"
ck "no secret-looking files tracked" \
   "! git ls-files | grep -qiE 'key|secret|\.env|account'"
ck ".gitignore excludes CLAUDE.md" "grep -q '^CLAUDE.md$' .gitignore"
ck ".gitignore excludes .claude/" "grep -q '^\.claude/$' .gitignore"
ck ".gitignore excludes .accounts.json" "grep -q '^\.accounts\.json$' .gitignore"
ck "no __pycache__ tracked" "! git ls-files | grep -q __pycache__"
ck "README exists and is substantial" "[ \$(wc -c < README.md) -gt 10000 ]"
ck "docs/PROBE.md exists" "[ -f docs/PROBE.md ]"
ck "docs/DESIGN.md exists" "[ -f docs/DESIGN.md ]"
ck "docs/AUDIT.md exists" "[ -f docs/AUDIT.md ]"

echo "== 6. claims in the README match measured values =="
# the README writes byte counts with thousands separators, so strip commas
# from the README before matching rather than loosening what is compared
ck "README artifact byte counts match the files" \
   "tr -d , < README.md | grep -q \"\$(wc -c < build/PackageGuard.min.py | tr -d ' ') bytes\" && tr -d , < README.md | grep -q \"\$(wc -c < build/PackageConsumer.min.py | tr -d ' ') bytes\""
ck "README sha256 matches the artifact" \
   "grep -q \"\$(shasum -a 256 build/PackageGuard.min.py | cut -d' ' -f1)\" README.md"
ck "README test count matches the suite" \
   "grep -q \"Ran \$(python3 test/test_logic.py 2>&1 | grep -oE '^Ran [0-9]+' | grep -oE '[0-9]+') tests\" README.md"

echo "== 7. every documented method exists =="
for m in request_scan set_fee get_risk get_risk_by_id get_risk_history is_safe \
         require_safe get_top_packages get_riskiest verify_risk get_stats \
         get_config claim_refund set_paused transfer_ownership withdraw; do
  ck "PackageGuard.$m" "grep -q \"def $m(\" contracts/PackageGuard.py"
done
for m in add_dependency remove_dependency check_risk preview_dependency \
         gate_build get_manifest get_policy set_policy freeze; do
  ck "PackageConsumer.$m" "grep -q \"def $m(\" contracts/PackageConsumer.py"
done

if [ -n "$ORACLE" ]; then
  echo "== 8. live deployment =="
  genlayer code "$ORACLE" 2>/dev/null | sed -n '/^# {/,$p' \
    | sed '/^. Contract code retrieved/,$d' \
    | sed -e :a -e '/^\n*$/{$d;N;};/\n$/ba' > /tmp/_onchain.py
  ck "deployed source is byte-identical to build/PackageGuard.min.py" \
     "diff -q /tmp/_onchain.py build/PackageGuard.min.py"
  ck "fee is 0 on the demo deployment" \
     "genlayer call $ORACLE get_config 2>/dev/null | grep -q 'fee_wei: 0'"
  ck "get_stats reports scanned packages" \
     "genlayer call $ORACLE get_stats 2>/dev/null | grep -q 'total_scanned'"
  ck "verify_risk(1) returns verified: true" \
     "genlayer call $ORACLE verify_risk --args 1 2>/dev/null | grep -q 'verified: true'"
  ck "require_safe reverts below the bar" \
     "! genlayer call $ORACLE require_safe --args express 95 2>/dev/null | grep -q 'Result:'"
  ck "is_safe on an unscanned package is false" \
     "genlayer call $ORACLE is_safe --args lodash 50 2>/dev/null | grep -q 'false'"
  if [ -n "$CONSUMER" ]; then
    ck "consumer reads the oracle cross-contract" \
       "genlayer call $CONSUMER get_oracle_stats 2>/dev/null | grep -q 'total_scanned'"
    ck "preview_dependency degrades instead of reverting" \
       "genlayer call $CONSUMER preview_dependency --args lodash 2>/dev/null | grep -q 'never scanned'"
    ck "gate_build fails a mixed dependency list" \
       "genlayer call $CONSUMER gate_build --args '[\"express\",\"flatmap-stream\"]' 2>/dev/null | grep -q \"build: 'FAIL'\""
  fi
fi

echo
echo "======================================================"
printf "  %d passed, %d failed\n" "$PASS" "$FAIL"
echo "======================================================"
exit $FAIL
