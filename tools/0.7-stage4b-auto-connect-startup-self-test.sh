#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
python3 -m unittest \
  tests.ui.test_auto_connect_options_stage4a_07 \
  tests.ui.test_auto_connect_startup_stage4b_07 \
  tests.connection.test_idle_quit \
  tests.release.test_stage8c3b_crash_recovery_polish \
  tests.release.test_stage8c3a7_ipv6_guard_lifecycle
printf '\nALL PIA BAZZITE 0.7 STAGE 4B AUTO-CONNECT STARTUP SELF-TESTS PASSED\n'
