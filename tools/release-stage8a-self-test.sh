#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8a-release-packaging-self-test.txt"
mkdir -p "$REPORT_DIR"

exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite Stage-8A 0.6.0 release/AppImage packaging audit self-test\n'
printf 'This test does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI.\n\n'

printf '%s\n' '--- Stage-8A release and helper-bundle tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/release" -p 'test_*.py' -v

printf '\n%s\n' '--- Current PIA Bazzite release self-test ---'
PYTHONPATH="$ROOT" python3 "$ROOT/self_test.py"

printf '\n%s\n' '--- Stage-7 final unprivileged regression gate ---'
bash "$ROOT/tools/kill-switch-crash-stage7d-self-test.sh"

printf '\nALL STAGE-8A RELEASE/PACKAGING AUDIT SELF-TESTS PASSED\n'
printf 'No host firewall, VPN connection, helper installation, GUI session, or physical-path sentinel was changed by this self-test.\n'
printf 'Report: %s\n' "$REPORT"
