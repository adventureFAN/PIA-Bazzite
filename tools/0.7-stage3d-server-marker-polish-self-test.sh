#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
python3 -m unittest tests.ui.test_server_markers_stage3d
printf '\nALL PIA BAZZITE 0.7 STAGE 3D SERVER-MARKER POLISH SELF-TESTS PASSED\n'
