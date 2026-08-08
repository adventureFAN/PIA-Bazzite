#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8c2-packaging-host-test.txt"
APP="$ROOT/dist/PIA-Bazzite-0.6.0-x86_64.AppImage"
SIDE="$APP.sha256"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

echo 'PIA Bazzite Stage-8C.2 packaging/release-hygiene host test'
echo 'This test builds and extracts an AppImage but does not use sudo/pkexec, install the helper, start a VPN, or change nftables.'
echo

echo '--- Build fresh development AppImage from isolated Podman staging ---'
PIA_BAZZITE_BUILD_MODE=development bash "$ROOT/packaging/build-appimage-podman.sh"
[[ -x "$APP" ]] || { echo "ERROR: expected AppImage not found: $APP" >&2; exit 1; }
[[ -f "$SIDE" ]] || { echo "ERROR: checksum sidecar not found: $SIDE" >&2; exit 1; }
(
  cd "$ROOT/dist"
  sha256sum --check "$(basename "$SIDE")"
)
echo 'PASS    Fresh 0.6.0 AppImage and portable SHA-256 sidecar verify.'

echo
echo '--- Extract and inspect provenance, metadata, notices, and runtime licenses ---'
TMP="$(mktemp -d "${TMPDIR:-/tmp}/pia-bazzite-stage8c2-package.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
(
  cd "$TMP"
  "$APP" --appimage-extract >/dev/null
)
EXTRACTED="$TMP/squashfs-root"
[[ -d "$EXTRACTED" ]] || { echo 'ERROR: AppImage extraction did not create squashfs-root.' >&2; exit 1; }
DOC="$EXTRACTED/usr/share/doc/pia-bazzite"
META="$EXTRACTED/usr/share/metainfo"
[[ -f "$DOC/BUILD_INFO.txt" ]] || { echo 'ERROR: BUILD_INFO.txt missing.' >&2; exit 1; }
grep -Fx 'PIA Bazzite version: 0.6.0' "$DOC/BUILD_INFO.txt" >/dev/null
grep -Fx 'Build mode: development' "$DOC/BUILD_INFO.txt" >/dev/null
grep -Fx 'Source commit: working-tree' "$DOC/BUILD_INFO.txt" >/dev/null
cmp -s \
  "$META/io.github.adventurefan.PIABazzite.metainfo.xml" \
  "$META/io.github.adventurefan.PIABazzite.appdata.xml"
[[ -f "$DOC/THIRD_PARTY_NOTICES.md" ]] || { echo 'ERROR: THIRD_PARTY_NOTICES.md missing.' >&2; exit 1; }
QTBASE_DE_COUNT="$(find "$EXTRACTED" -type f -name 'qtbase_de.qm' -print | wc -l)"
[[ "$QTBASE_DE_COUNT" -ge 1 ]] || { echo 'ERROR: qtbase_de.qm missing from the AppImage runtime.' >&2; exit 1; }
echo 'PASS    German Qt standard-dialog translation is bundled.'
[[ -f "$DOC/third-party-python/COMPONENTS.txt" ]] || { echo 'ERROR: generated third-party component inventory missing.' >&2; exit 1; }
python3 - "$DOC/third-party-python/COMPONENTS.txt" <<'PY_COMPONENTS'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
found = set()
for line in text.splitlines():
    if not line.startswith("- "):
        continue
    name = line[2:].split(" ", 1)[0]
    found.add(re.sub(r"[-_.]+", "-", name).lower())
required = {"pyside6-essentials", "keyring", "secretstorage", "requests"}
missing = sorted(required - found)
if missing:
    raise SystemExit("Missing required runtime component(s): " + ", ".join(missing))
print("required runtime roots present: " + ", ".join(sorted(required)))
PY_COMPONENTS
LICENSE_COUNT="$(find "$DOC/third-party-python" -type f \
  \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' -o -iname 'AUTHORS*' \) \
  | wc -l)"
[[ "$LICENSE_COUNT" -gt 0 ]] || { echo 'ERROR: generated third-party tree contains no license/notice material.' >&2; exit 1; }
PYSIDE_LICENSE_DIR="$DOC/third-party-python/PySide6-Qt"
for required_license in LGPL-3.0.txt GPL-3.0.txt GPL-2.0.txt README.txt; do
  [[ -f "$PYSIDE_LICENSE_DIR/$required_license" ]] || {
    echo "ERROR: bundled PySide6/Qt license material is missing: $required_license" >&2
    exit 1
  }
done
printf '%s  %s\n' \
  'e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118' \
  "$PYSIDE_LICENSE_DIR/LGPL-3.0.txt" | sha256sum --check --status || { echo 'ERROR: bundled LGPL-3.0 text hash mismatch.' >&2; exit 1; }
printf '%s  %s\n' \
  '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986' \
  "$PYSIDE_LICENSE_DIR/GPL-3.0.txt" | sha256sum --check --status || { echo 'ERROR: bundled GPL-3.0 text hash mismatch.' >&2; exit 1; }
printf '%s  %s\n' \
  'edaef632cbb643e4e7a221717a6c441a4c1a7c918e6e4d56debc3d8739b233f6' \
  "$PYSIDE_LICENSE_DIR/GPL-2.0.txt" | sha256sum --check --status || { echo 'ERROR: bundled GPL-2.0 text hash mismatch.' >&2; exit 1; }
echo 'PASS    Canonical PySide6/Qt open-source license texts are present and hash-verified.'
if [[ -n "${HOME:-}" ]] && grep -RIlF "$HOME" "$EXTRACTED" >/dev/null 2>&1; then
  echo 'ERROR: local development home path found in AppImage.' >&2
  exit 1
fi
echo "PASS    AppImage provenance, AppStream aliases, notices, component inventory, and $LICENSE_COUNT license/notice files are present."

echo
echo '--- Smoke-test runtime version without a privileged helper action ---'
APPIMAGE_EXTRACT_AND_RUN=1 "$APP" --version | grep -F '0.6.0' >/dev/null
echo 'PASS    Extract-and-run version smoke test reports 0.6.0.'

echo
echo 'ALL STAGE-8C.2 PACKAGING/RELEASE HYGIENE HOST TESTS PASSED'
echo 'No helper installation, host firewall, VPN connection, privileged GUI session, or physical-path sentinel was changed by this test.'
echo "Report: $REPORT"
