#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

"$PYTHON" -m unittest -v \
  tests.ui.test_stage7d3_source_autostart_venv_07 \
  tests.ui.test_autostart_tray_stage4c_07 \
  tests.ui.test_auto_connect_startup_stage4b_07 \
  tests.ui.test_stage7b3_light_icon_contrast_07

printf '\nALL PIA BAZZITE 0.7 STAGE 7D.3 SOURCE-AUTOSTART HOTFIX SELF-TESTS PASSED\n'
