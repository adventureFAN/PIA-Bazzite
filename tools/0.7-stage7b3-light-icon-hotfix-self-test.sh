#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m unittest -v \
  tests.ui.test_stage7b3_light_icon_contrast_07 \
  tests.ui.test_auto_connect_options_stage4a_07 \
  tests.ui.test_stage6a_ui_polish_07 \
  tests.ui.test_stage6b_options_redesign_07 \
  tests.ui.test_stage6b_kde_polish_07

echo
echo "ALL PIA BAZZITE 0.7 STAGE 7B.3 LIGHT-ICON HOTFIX SELF-TESTS PASSED"
