#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
python3 -m unittest \
  tests.ui.test_auto_connect_options_stage4a_07 \
  tests.ui.test_options_dialog_stage3a \
  tests.ui.test_public_network_provider_options_stage3c \
  tests.ui.test_server_markers_stage3d
printf '\nALL PIA BAZZITE 0.7 STAGE 4A AUTO-CONNECT OPTIONS SELF-TESTS PASSED\n'
