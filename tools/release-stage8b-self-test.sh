#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8b-helper-installation-self-test.txt"
mkdir -p "$REPORT_DIR"

exec > >(tee "$REPORT") 2>&1

echo "PIA Bazzite Stage-8B packaged helper install/upgrade gate self-test"
echo "This test does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI."
echo

echo "--- Python and shell syntax ---"
python3 -m compileall -q "$ROOT/pia_bazzite" "$ROOT/tests/release"
bash -n "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
bash -n "$ROOT/packaging/build-appimage.sh"
echo "PASS  syntax checks"

echo
echo "--- Stage-8A/8B release and helper installation tests ---"
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.release.test_stage8a_packaging \
  tests.release.test_stage8b_helper_installation

echo
echo "--- Full Stage-7 unprivileged security/regression gate ---"
bash "$ROOT/tools/kill-switch-crash-stage7d-self-test.sh"

echo
echo "ALL STAGE-8B PACKAGED HELPER INSTALL/UPGRADE GATE SELF-TESTS PASSED"
echo "No host firewall, VPN connection, helper installation, GUI session, AppImage mount, or physical-path sentinel was changed by this self-test."
echo "Report: $REPORT"
