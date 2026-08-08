#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage5-connection"
REPORT="$REPORT_DIR/pia-kill-switch-connection-stage5c-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-5C real-GUI integration self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not use sudo, pkexec, networking, NetworkManager, or nftables.\n\n'

printf '%s\n' '--- Python syntax ---'
mapfile -t python_files < <(
  find "$ROOT/pia_bazzite" "$ROOT/helper" "$ROOT/tests" -type f -name '*.py' -print
  printf '%s\n' "$ROOT/tools/pia-bazzite-stage5b-host-driver.py"
)
python3 -m py_compile "${python_files[@]}"
printf 'PASS  compiled %d Python files\n' "${#python_files[@]}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  env -u PYTHONPATH QT_QPA_PLATFORM=offscreen \
    "$ROOT/.venv/bin/python" \
    "$ROOT/tools/pia-bazzite-stage4c-runtime-preview.py" \
    --language de --theme light --smoke-test >/dev/null
  printf 'PASS  real MainWindow preview passed offscreen\n\n'
else
  printf 'SKIP  real MainWindow runtime smoke test (.venv Python not found)\n\n'
fi

printf '%s\n' '--- Shell syntax ---'
for script in \
  "$ROOT/tools/kill-switch-connection-stage5a-self-test.sh" \
  "$ROOT/tools/kill-switch-connection-stage5b-self-test.sh" \
  "$ROOT/tools/kill-switch-connection-stage5b-host-test.sh" \
  "$ROOT/tools/kill-switch-connection-stage5b-emergency-reset.sh" \
  "$ROOT/tools/kill-switch-connection-stage5c-self-test.sh" \
  "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
do
  bash -n "$script"
done
printf 'PASS  stage-5 shell and installer scripts parse\n\n'

printf '%s\n' '--- Stage-5 connection, host-boundary, and GUI-integration tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/connection" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing UI, client, helper, and Polkit regression tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/ui" -p 'test_*.py' -v
PYTHONPATH="$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/client" -p 'test_*.py' -v
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/helper" -p 'test_*.py' -v
PYTHONPATH="$ROOT/helper:$ROOT" python3 -m unittest discover \
  -s "$ROOT/tests/polkit" -p 'test_*.py' -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite release regression self-test ---'
python3 "$ROOT/self_test.py"
printf '\nALL STAGE-5C GUI INTEGRATION SELF-TESTS PASSED\n'
printf 'No host firewall or VPN connection was changed by this self-test.\n'
printf 'Report: %s\n' "$REPORT"
