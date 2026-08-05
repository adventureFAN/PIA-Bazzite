#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage3-client"
REPORT="$REPORT_DIR/pia-kill-switch-session-stage3c-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-3C single-authorization session self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not use sudo, pkexec, networking, NetworkManager, or nftables.\n\n'

printf '%s\n' '--- Python syntax ---'
mapfile -t python_files < <(
  find "$ROOT/pia_bazzite" "$ROOT/tests/client" "$ROOT/tests/polkit" -type f -name '*.py' -print
  printf '%s\n' \
    "$ROOT/helper/pia-bazzite-kill-switch-helper-installed" \
    "$ROOT/helper/pia-bazzite-kill-switch-session-installed" \
    "$ROOT/helper/pia_bazzite_kill_switch_helper/session_entry.py" \
    "$ROOT/tools/pia-bazzite-stage3c-session-netns-bridge.py" \
    "$ROOT/tools/pia-bazzite-stage3c-session-driver.py"
)
python3 -m py_compile "${python_files[@]}"
printf 'PASS  compiled %d Python files\n\n' "${#python_files[@]}"

printf '%s\n' '--- Shell syntax ---'
bash -n \
  "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" \
  "$ROOT/tools/kill-switch-session-stage3c-self-test.sh" \
  "$ROOT/tools/kill-switch-session-stage3c-namespace-test.sh"
printf 'PASS  stage-3C shell scripts parse\n\n'

printf '%s\n' '--- Client and session unit tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/client" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Helper, protocol, installation, and Polkit regression tests ---'
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/helper" -p 'test_*.py' -v
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/polkit" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite v0.5.0 regression self-test ---'
python3 "$ROOT/self_test.py"
printf '\nALL STAGE-3C UNPRIVILEGED SELF-TESTS PASSED\n'
printf 'Report: %s\n' "$REPORT"
