#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage2-polkit"
REPORT="$REPORT_DIR/pia-kill-switch-helper-stage2d-protocol-self-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-2D.1 helper protocol self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not use sudo, pkexec, networking, NetworkManager, or nftables.\n\n'

printf '%s\n' '--- Python syntax ---'
python3 - "$ROOT" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
files = [
    root / "helper/pia-bazzite-kill-switch-helper-installed",
    *sorted((root / "helper/pia_bazzite_kill_switch_helper").glob("*.py")),
    *sorted((root / "tests/helper").glob("*.py")),
    *sorted((root / "tests/polkit").glob("*.py")),
]
for path in files:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print(f"PASS  compiled {len(files)} Python files")
PY
printf '\n'

printf '%s\n' '--- Shell syntax ---'
bash -n "$ROOT/tools/kill-switch-helper-stage2d-protocol-self-test.sh"
printf 'PASS  stage-2D.1 shell script parses\n\n'

printf '%s\n' '--- Helper protocol and regression unit tests ---'
PYTHONPATH="$ROOT" python3 -m unittest discover -s "$ROOT/tests/helper" -v
PYTHONPATH="$ROOT" python3 -m unittest discover -s "$ROOT/tests/polkit" -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite release regression self-test ---'
"$ROOT/.venv/bin/python" "$ROOT/self_test.py"
printf '\n'

printf 'ALL STAGE-2D.1 PROTOCOL SELF-TESTS PASSED\n'
printf 'Report: %s\n' "$REPORT"
