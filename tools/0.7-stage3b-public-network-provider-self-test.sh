#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

PYTHON="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
    PYTHON="$ROOT/venv/bin/python"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" -m unittest -v tests.connection.test_public_network_providers
"$PYTHON" -m unittest -v tests.ui.test_options_dialog_stage3a

printf '\nALL PIA BAZZITE 0.7 STAGE 3B PUBLIC-NETWORK PROVIDER CORE SELF-TESTS PASSED\n'
