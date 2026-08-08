#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8c2-hardening-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

echo 'PIA Bazzite Stage-8C.2 code-audit hardening self-test'
echo 'This test does not use sudo, pkexec, networking, NetworkManager, nftables, the real GUI, or an AppImage mount.'
echo

echo '--- Syntax and fixed release boundaries ---'
python3 -m compileall -q \
  "$ROOT/pia_bazzite" \
  "$ROOT/tests/release" \
  "$ROOT/tests/connection/test_network_manager_reconnect.py" \
  "$ROOT/tests/connection/test_emergency_reset.py" \
  "$ROOT/tests/connection/test_ipv6_guard_lifecycle.py" \
  "$ROOT/tests/release/test_stage8c3b_crash_recovery_polish.py" \
  "$ROOT/tests/release/test_stage8c3a7_ipv6_guard_lifecycle.py" \
  "$ROOT/packaging/collect_third_party_licenses.py"
bash -n "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
bash -n "$ROOT/tools/release-stage8c2-self-test.sh"
bash -n "$ROOT/tools/release-unprivileged-gate.sh"
bash -n "$ROOT/tools/release-stage8c2-packaging-host-test.sh"
bash -n "$ROOT/tools/pia-bazzite-network-debug.sh"
bash -n "$ROOT/tools/pia-bazzite-ipv6-guard-helper-namespace-test.sh"
bash -n "$ROOT/tools/pia-bazzite-ipv6-guard-runtime-check.sh"
bash -n "$ROOT/packaging/build-appimage.sh"
bash -n "$ROOT/packaging/build-appimage-podman.sh"
echo 'PASS  syntax checks'

echo
echo '--- Stage-8C.2 targeted audit regression tests ---'
PYTHONPATH="$ROOT" python3 -m unittest -v \
  tests.release.test_stage8a_packaging \
  tests.release.test_stage8b_helper_installation \
  tests.release.test_stage8b2_appimage_host_gate \
  tests.release.test_stage8c2_hardening \
  tests.release.test_stage8c2_packaging_hygiene \
  tests.release.test_stage8c3_ipv6_guard \
  tests.release.test_stage8c3a7_ipv6_guard_lifecycle \
  tests.release.test_stage8c3b_crash_recovery_polish \
  tests.connection.test_emergency_reset \
  tests.connection.test_network_manager_reconnect \
  tests.connection.test_ipv6_guard_lifecycle

echo
echo '--- Full existing Stage-8B.2 / Stage-7 security regression gate ---'
bash "$ROOT/tools/release-stage8b2-self-test.sh"

echo
echo 'ALL STAGE-8C.2 CODE-AUDIT HARDENING SELF-TESTS PASSED'
echo 'No helper installation, host firewall, VPN connection, real GUI session, AppImage mount, or physical-path sentinel was changed by this self-test.'
echo "Report: $REPORT"
