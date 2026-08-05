#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
    echo "PIA Bazzite is not set up yet."
    echo "Run ./setup.sh once, then start the app again with ./run.sh."
    exit 1
fi

exec .venv/bin/python main.py "$@"
