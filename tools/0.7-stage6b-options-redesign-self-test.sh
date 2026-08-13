#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

"$PYTHON" -m unittest \
  tests.ui.test_stage6b_options_redesign_07 \
  tests.ui.test_stage6b_kde_polish_07 \
  tests.ui.test_stage6a_ui_polish_07 \
  tests.ui.test_options_dialog_stage3a \
  tests.ui.test_public_network_provider_options_stage3c \
  tests.ui.test_auto_connect_options_stage4a_07 \
  tests.ui.test_server_markers_stage3d \
  tests.ui.test_server_favorites_stage2b \
  tests.ui.test_server_favorites_stage2c \
  tests.ui.test_autostart_tray_stage4c_07 \
  tests.ui.test_network_state_detection_stage5a_07

printf '\nALL PIA BAZZITE 0.7 STAGE 6B OPTIONS REDESIGN SELF-TESTS PASSED\n'
