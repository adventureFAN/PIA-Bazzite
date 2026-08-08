#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage4-ui"
REPORT="$REPORT_DIR/pia-kill-switch-ui-stage4a-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-4A kill-switch UI-state self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not use sudo, pkexec, networking, NetworkManager, or nftables.\n\n'

printf '%s\n' '--- Python syntax ---'
mapfile -t python_files < <(
  find "$ROOT/pia_bazzite" "$ROOT/tests/ui" -type f -name '*.py' -print
  printf '%s\n' "$ROOT/tools/pia-bazzite-stage4a-state-preview.py"
)
python3 -m py_compile "${python_files[@]}"
printf 'PASS  compiled %d Python files\n' "${#python_files[@]}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  env -u PYTHONPATH "$ROOT/.venv/bin/python" \
    "$ROOT/tools/pia-bazzite-stage4a-state-preview.py" --help >/dev/null
  printf 'PASS  preview starts directly from tools/ without PYTHONPATH\n\n'
else
  printf 'SKIP  direct preview smoke test (.venv Python not found)\n\n'
fi

printf '%s\n' '--- Shell syntax ---'
bash -n "$ROOT/tools/kill-switch-ui-stage4a-self-test.sh"
printf 'PASS  stage-4A shell script parses\n\n'

printf '%s\n' '--- UI state-model and static safety tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/ui" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing client, helper, and Polkit regression tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/client" -p 'test_*.py' -v
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/helper" -p 'test_*.py' -v
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/polkit" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite release regression self-test ---'
python3 "$ROOT/self_test.py"
printf '\nALL STAGE-4A UI-STATE SELF-TESTS PASSED\n'
printf 'Report: %s\n' "$REPORT"
