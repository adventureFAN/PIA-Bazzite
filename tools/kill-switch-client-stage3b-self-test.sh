#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage3-client"
REPORT="$REPORT_DIR/pia-kill-switch-client-stage3b-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-3B real-client harness self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not use sudo, pkexec, networking, NetworkManager, or nftables.\n\n'

printf '%s\n' '--- Python syntax ---'
mapfile -t python_files < <(
  find "$ROOT/pia_bazzite" "$ROOT/tests/client" -type f -name '*.py' -print
  printf '%s\n' \
    "$ROOT/tools/pia-bazzite-stage3-client-netns-bridge.py" \
    "$ROOT/tools/pia-bazzite-stage3-client-driver.py" \
    "$ROOT/tools/pia-bazzite-stage3-client-probe.py" \
    "$ROOT/tools/pia-bazzite-stage3-client-process-shim.py"
)
python3 -m py_compile "${python_files[@]}"
printf 'PASS  compiled %d Python files\n\n' "${#python_files[@]}"

printf '%s\n' '--- Shell syntax ---'
bash -n \
  "$ROOT/tools/kill-switch-client-stage3b-self-test.sh" \
  "$ROOT/tools/kill-switch-client-stage3b-namespace-test.sh"
printf 'PASS  stage-3B shell scripts parse\n\n'

printf '%s\n' '--- Kill-switch client and stage-3B harness unit tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/client" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing helper, protocol, and Polkit regression tests ---'
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/helper" -p 'test_*.py' -v
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/polkit" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite release regression self-test ---'
python3 "$ROOT/self_test.py"
printf '\nALL STAGE-3B UNPRIVILEGED SELF-TESTS PASSED\n'
printf 'Report: %s\n' "$REPORT"
