#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

"$PYTHON" -m unittest \
  tests.ui.test_autostart_tray_stage4c_07 \
  tests.ui.test_auto_connect_startup_stage4b_07 \
  tests.ui.test_auto_connect_options_stage4a_07 \
  tests.ui.test_server_favorites_stage2c \
  tests.ui.test_options_dialog_stage3a \
  tests.connection.test_stage6c2_static

printf '\nALL PIA BAZZITE 0.7 STAGE 4C AUTOSTART/TRAY POLISH SELF-TESTS PASSED\n'
