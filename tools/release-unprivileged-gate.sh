#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo 'PIA Bazzite authoritative unprivileged release gate'
echo 'This gate is the CI/release entry point. It must not use sudo, pkexec, NetworkManager, nftables, or the real GUI.'
echo

bash "$ROOT/tools/release-stage8c2-self-test.sh"

python3 - "$ROOT" <<'PY_GATE'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
app_id = "io.github.adventurefan.PIABazzite"
ET.parse(root / "packaging" / f"{app_id}.metainfo.xml")
print("PASS  release metadata XML parses")
PY_GATE

echo
echo 'ALL AUTHORITATIVE UNPRIVILEGED RELEASE GATES PASSED'
