#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Creating the private Python environment / Python-Umgebung wird erstellt …"
python3 -m venv .venv

echo "Installing dependencies / Abhängigkeiten werden installiert …"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo
echo "Setup complete / Einrichtung abgeschlossen."
echo "Start PIA Bazzite with / Starte PIA Bazzite mit:"
echo "./run.sh"
