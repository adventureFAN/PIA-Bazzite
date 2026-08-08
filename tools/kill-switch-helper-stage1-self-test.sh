#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage1-helper"
REPORT="${1:-$REPORT_DIR/pia-kill-switch-helper-stage1-self-test.txt}"

mkdir -p "$(dirname "$REPORT")"
exec > >(tee "$REPORT") 2>&1

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

printf 'PIA Bazzite stage-1 helper self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not change networking or nftables.\n\n'

cd "$ROOT"

printf '%s\n' '--- Python syntax ---'
"$PYTHON" -m py_compile \
  helper/pia-bazzite-kill-switch-helper \
  helper/pia_bazzite_kill_switch_helper/*.py \
  tests/helper/*.py
printf 'PASS  helper and tests compile\n\n'

printf '%s\n' '--- Shell syntax ---'
bash -n tools/kill-switch-helper-stage1-self-test.sh
bash -n tools/kill-switch-helper-stage1-namespace-test.sh
printf 'PASS  stage-1 shell scripts parse\n\n'

printf '%s\n' '--- Restricted helper unit tests ---'
"$PYTHON" -m unittest discover -s tests/helper -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite release regression self-test ---'
"$PYTHON" self_test.py
printf '\nALL STAGE-1 SELF-TESTS PASSED\n'
printf 'Report: %s\n' "$REPORT"
