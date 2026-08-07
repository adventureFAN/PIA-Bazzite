#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage7-crash-recovery"
REPORT="$REPORT_DIR/pia-kill-switch-crash-stage7d-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-7D final adversarial recovery gate self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not use privilege escalation, networking, NetworkManager, nftables, or the real GUI.\n\n'

printf '%s\n' '--- Python syntax ---'
mapfile -t python_files < <(
  find "$ROOT/pia_bazzite" "$ROOT/helper" "$ROOT/tests" "$ROOT/tools" \
    -type f -name '*.py' -print | sort
)
python3 -m py_compile "${python_files[@]}"
printf 'PASS  compiled %d Python files\n' "${#python_files[@]}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  env -u PYTHONPATH QT_QPA_PLATFORM=offscreen \
    "$ROOT/.venv/bin/python" \
    "$ROOT/tools/pia-bazzite-stage4c-runtime-preview.py" \
    --language de --theme light --smoke-test >/dev/null
  printf 'PASS  existing MainWindow preview passed offscreen\n\n'
else
  printf 'SKIP  existing MainWindow runtime smoke test (.venv Python not found)\n\n'
fi

printf '%s\n' '--- Shell syntax ---'
while IFS= read -r script; do
  bash -n "$script"
done < <(find "$ROOT/tools" -maxdepth 1 -type f -name '*.sh' -print | sort)
printf 'PASS  all kill-switch and installer shell scripts parse\n\n'

printf '%s\n' '--- Stage-5/6 connection and complete Stage-7 crash-recovery regression tests ---'
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

printf '%s\n' '--- Existing PIA Bazzite v0.5.0 regression self-test ---'
python3 "$ROOT/self_test.py"
printf '\nALL STAGE-7D FINAL ADVERSARIAL RECOVERY GATE SELF-TESTS PASSED\n'
printf 'No host firewall, VPN connection, GUI session, crash-recovery path, or physical-path sentinel was changed by this self-test.\n'
printf 'Report: %s\n' "$REPORT"
