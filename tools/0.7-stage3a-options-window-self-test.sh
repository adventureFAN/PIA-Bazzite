#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo 'PIA Bazzite 0.7 Stage 3A Options-window foundation self-test'
echo 'This test does not use sudo, pkexec, networking, NetworkManager, nftables, the real GUI, a real tray, or an AppImage.'
echo

python3 -m compileall -q \
  "$ROOT/pia_bazzite/gui.py" \
  "$ROOT/pia_bazzite/options_dialog.py" \
  "$ROOT/tests/ui/test_options_dialog_stage3a.py"

echo '--- Focused Stage 3A Options-window regression ---'
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.ui.test_options_dialog_stage3a

echo
echo '--- Existing release self-test ---'
PYTHONPATH="$ROOT" python3 "$ROOT/self_test.py"

echo
echo 'ALL PIA BAZZITE 0.7 STAGE 3A OPTIONS-WINDOW FOUNDATION SELF-TESTS PASSED'
echo 'No real settings, credentials, Kill Switch state, network state, helper session, firewall, NetworkManager state, GUI session, or tray was changed by this self-test.'
