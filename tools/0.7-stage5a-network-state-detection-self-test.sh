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
  tests.connection.test_physical_network_state_stage5a_07 \
  tests.ui.test_network_state_detection_stage5a_07 \
  tests.ui.test_auto_connect_startup_stage4b_07 \
  tests.ui.test_autostart_tray_stage4c_07

printf '\n--- Current NetworkManager physical-underlay probe ---\n'
"$PYTHON" - <<'PY'
from pia_bazzite import network_manager
print("physical_network_available =", network_manager.physical_network_available())
PY

printf '\nALL PIA BAZZITE 0.7 STAGE 5A NETWORK-STATE DETECTION SELF-TESTS PASSED\n'
