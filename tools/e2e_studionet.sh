#!/usr/bin/env bash
# Scan a list of real packages through a deployed PackageGuard, respecting the
# contract's own 300-second per-wallet rate limit.
#
#   bash tools/e2e_studionet.sh <oracle-address> [package ...]
#
# The pacing is not politeness toward npm - the registry is fine with this - it
# is the contract's RATE_LIMIT_SECONDS, which is a module constant precisely so
# that no owner can clear the way for one address to flood the leaderboard.
#
# request_scan never raises once value is attached: it returns a REJECTED object
# and credits the fee back. So "write executed" does NOT mean "scored", and this
# script reads the record back and says which happened.
set -uo pipefail

ORACLE="${1:?usage: e2e_studionet.sh <oracle-address> [package ...]}"
shift
PKGS=("$@")
if [ ${#PKGS[@]} -eq 0 ]; then
  PKGS=(express left-pad event-stream flatmap-stream esbuild node-sass chalk)
fi

GAP=310   # RATE_LIMIT_SECONDS plus a margin
SCORED=0
MISSED=()

for i in "${!PKGS[@]}"; do
  PKG="${PKGS[$i]}"
  echo "=================================================================="
  echo "==> [$((i+1))/${#PKGS[@]}] request_scan $PKG   ($(date -u +%H:%M:%S)Z)"
  START=$(date +%s)
  genlayer write "$ORACLE" request_scan --args "$PKG" 2>&1 | tail -2
  echo "--- get_risk $PKG"
  OUT=$(genlayer call "$ORACLE" get_risk --args "$PKG" 2>&1 | sed -n '/Result:/,$p')
  echo "$OUT"
  if echo "$OUT" | grep -q "found: true"; then
    SCORED=$((SCORED+1))
  else
    echo "!!! $PKG was NOT scored - request_scan returned REJECTED (rate limit,"
    echo "!!! cooldown, or a refusal). Re-run it once the window has passed."
    MISSED+=("$PKG")
  fi
  END=$(date +%s)
  if [ $((i+1)) -lt ${#PKGS[@]} ]; then
    ELAPSED=$((END-START))
    WAIT=$((GAP-ELAPSED))
    if [ $WAIT -gt 0 ]; then
      echo "==> waiting ${WAIT}s for the per-wallet rate limit"
      sleep $WAIT
    fi
  fi
done

echo "=================================================================="
echo "==> scored $SCORED of ${#PKGS[@]}"
if [ ${#MISSED[@]} -gt 0 ]; then
  echo "==> not scored: ${MISSED[*]}"
fi
echo "--- get_riskiest 10"
genlayer call "$ORACLE" get_riskiest --args 10 2>&1 | sed -n '/Result:/,$p'
echo "--- get_stats"
genlayer call "$ORACLE" get_stats 2>&1 | sed -n '/Result:/,$p'
echo "==> done"
