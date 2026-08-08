#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8b2-appimage-host-gate-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

echo 'PIA Bazzite Stage-8B.2 real AppImage host-gate self-test'
echo 'This test does not build or mount an AppImage and does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI.'
echo

echo '--- Syntax ---'
python3 -m compileall -q "$ROOT/pia_bazzite" "$ROOT/tests/release" "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py"
bash -n "$ROOT/packaging/build-appimage.sh"
bash -n "$ROOT/tools/release-stage8b2-host-test.sh"
bash -n "$ROOT/tools/release-stage8b2-emergency-restore.sh"
echo 'PASS  syntax checks'

echo
echo '--- Stage-8A/8B/8B.2 release tests ---'
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.release.test_stage8a_packaging \
  tests.release.test_stage8b_helper_installation \
  tests.release.test_stage8b2_appimage_host_gate

echo
echo '--- Existing Stage-8B and Stage-7 regression gate ---'
bash "$ROOT/tools/release-stage8b-self-test.sh"

echo
echo 'ALL STAGE-8B.2 REAL APPIMAGE HOST-GATE SELF-TESTS PASSED'
echo 'No AppImage build/mount, helper installation, host firewall, VPN connection, GUI session, or physical-path sentinel was changed by this self-test.'
echo "Report: $REPORT"
