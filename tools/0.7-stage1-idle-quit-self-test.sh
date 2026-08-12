#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo 'PIA Bazzite 0.7 Stage 1 clean-idle quit self-test'
echo 'This test does not use sudo, pkexec, networking, NetworkManager, nftables, the real GUI, or an AppImage.'
echo

python3 -m compileall -q \
  "$ROOT/pia_bazzite/gui.py" \
  "$ROOT/tests/connection/test_idle_quit.py"

echo '--- Focused Stage 1 regression tests ---'
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.connection.test_idle_quit \
  tests.release.test_stage8c3b_crash_recovery_polish \
  tests.connection.test_stage6c2_static \
  tests.connection.test_stage7b_static

echo
echo 'ALL PIA BAZZITE 0.7 STAGE 1 CLEAN-IDLE QUIT SELF-TESTS PASSED'
echo 'No helper session, Polkit prompt, VPN connection, firewall, NetworkManager state, or GUI session was changed by this self-test.'
