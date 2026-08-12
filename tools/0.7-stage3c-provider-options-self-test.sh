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
"$PYTHON" -m unittest -v tests.ui.test_public_network_provider_options_stage3c

printf '\nALL PIA BAZZITE 0.7 STAGE 3C PROVIDER-OPTIONS SELF-TESTS PASSED\n'
