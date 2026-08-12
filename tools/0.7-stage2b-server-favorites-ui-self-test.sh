#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo 'PIA Bazzite 0.7 Stage 2B server-favorites UI self-test'
echo 'This test does not use sudo, pkexec, networking, NetworkManager, nftables, the real GUI, or an AppImage.'
echo

python3 -m compileall -q \
  "$ROOT/pia_bazzite/gui.py" \
  "$ROOT/pia_bazzite/region_favorites.py" \
  "$ROOT/tests/connection/test_region_favorites.py" \
  "$ROOT/tests/ui/test_server_favorites_stage2b.py"

echo '--- Stage 2A favorites-core regression ---'
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.connection.test_region_favorites

echo
echo '--- Focused Stage 2B UI/source regression ---'
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.ui.test_server_favorites_stage2b

echo
echo '--- Existing release self-test ---'
PYTHONPATH="$ROOT" python3 "$ROOT/self_test.py"

echo
echo 'ALL PIA BAZZITE 0.7 STAGE 2B SERVER-FAVORITES UI SELF-TESTS PASSED'
echo 'No real settings, server list, network state, helper session, firewall, NetworkManager state, or GUI session was changed by this self-test.'
