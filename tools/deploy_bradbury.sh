#!/usr/bin/env bash
# Deploy PackageGuard + PackageConsumer to Bradbury testnet.
#
# Run from the repository root:   bash tools/deploy_bradbury.sh
#
# Needs a funded Bradbury account. Deploys the SAME artifacts that are live on
# Studionet - verify with `shasum -a 256 build/*.min.py` against deployments.json
# before and after.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> artifact checksums (must match deployments.json)"
shasum -a 256 build/PackageGuard.min.py build/PackageConsumer.min.py

echo
echo "==> switching to Bradbury"
genlayer network set testnet-bradbury

echo
echo "==> deploying PackageGuard"
genlayer deploy --contract build/PackageGuard.min.py 2>&1 | tee /tmp/pg_deploy.log

ORACLE=$(grep -oE "0x[a-fA-F0-9]{40}" /tmp/pg_deploy.log | tail -1)
if [ -z "$ORACLE" ]; then
  echo "!! could not read the oracle address from the deploy output" >&2
  exit 1
fi
echo
echo "==> PackageGuard deployed at $ORACLE"

echo
echo "==> setting the demo fee to 0"
# The genlayer CLI hardcodes `value: 0n` on every write, so there is no way to
# attach payable value from the command line. A non-zero fee would make
# request_scan uncallable from the CLI. set_fee is owner-only, 0..0.1 GEN.
genlayer write "$ORACLE" set_fee --args 0

echo
echo "==> deploying PackageConsumer pointed at $ORACLE"
genlayer deploy --contract build/PackageConsumer.min.py --args "$ORACLE" 2>&1 \
  | tee /tmp/pc_deploy.log

CONSUMER=$(grep -oE "0x[a-fA-F0-9]{40}" /tmp/pc_deploy.log | tail -1)

echo
echo "======================================================================"
echo "  PackageGuard      $ORACLE"
echo "  PackageConsumer   $CONSUMER"
echo "======================================================================"
echo
echo "Smoke test (request_scan is rate limited to one per wallet per 300s):"
echo "  genlayer call  $ORACLE get_config"
echo "  genlayer write $ORACLE request_scan --args express"
echo "  genlayer call  $ORACLE get_risk --args express"
echo "  genlayer call  $ORACLE verify_risk --args 1"
echo "  genlayer call  $CONSUMER get_policy"
echo "  genlayer call  $CONSUMER get_oracle_stats"
echo "  genlayer write $CONSUMER add_dependency --args express"
echo "  genlayer call  $CONSUMER get_manifest"
echo
echo "Score several packages with the pacing the rate limiter requires:"
echo "  bash tools/e2e_studionet.sh $ORACLE left-pad event-stream flatmap-stream"
echo
echo "Verify the deployed source matches the local artifact:"
echo "  genlayer code $ORACLE | diff - build/PackageGuard.min.py"
echo
echo "Switch back to Studionet with:  genlayer network set studionet"
