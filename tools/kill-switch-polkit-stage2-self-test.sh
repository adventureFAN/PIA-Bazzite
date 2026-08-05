#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage2-polkit"
REPORT="$REPORT_DIR/pia-kill-switch-polkit-stage2-self-test.txt"
mkdir -p "$REPORT_DIR"

run_tests() {
  echo "PIA Bazzite stage-2 Polkit self-test"
  echo "Generated: $(date --iso-8601=seconds)"
  echo "This test does not use sudo, pkexec, networking, NetworkManager, or nftables."
  echo

  echo "--- Python syntax ---"
  /usr/bin/python3 -m py_compile \
    "$ROOT/helper/pia-bazzite-polkit-probe" \
    "$ROOT/tests/polkit/test_probe.py"
  echo "PASS  stage-2 probe and tests compile"
  echo

  echo "--- Shell syntax ---"
  /usr/bin/bash -n \
    "$ROOT/tools/pia-bazzite-stage2-polkit-probe-installer.sh" \
    "$ROOT/tools/kill-switch-polkit-stage2-preflight.sh" \
    "$ROOT/tools/kill-switch-polkit-stage2-self-test.sh" \
    "$ROOT/tools/kill-switch-polkit-stage2-auth-test.sh"
  echo "PASS  stage-2 shell scripts parse"
  echo

  echo "--- Network-free Polkit probe unit tests ---"
  cd "$ROOT"
  /usr/bin/python3 -m unittest discover -s tests/polkit -v
  echo

  echo "--- Existing stage-1 helper regression tests ---"
  /usr/bin/python3 -m unittest discover -s tests/helper -v
  echo


  echo "ALL STAGE-2 UNPRIVILEGED SELF-TESTS PASSED"
}

run_tests 2>&1 | tee "$REPORT"
echo "Report: $REPORT"
