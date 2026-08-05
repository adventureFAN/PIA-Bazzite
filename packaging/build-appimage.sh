#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="0.5.0"
APP_ID="io.github.adventurefan.PIABazzite"
ARCH="x86_64"
BUILD_DIR="$ROOT/build/appimage"
VENV="$BUILD_DIR/venv"
APPDIR="$BUILD_DIR/PIA-Bazzite.AppDir"
DIST_DIR="$ROOT/dist"
OUTPUT="$DIST_DIR/PIA-Bazzite-${VERSION}-${ARCH}.AppImage"

mkdir -p "$BUILD_DIR" "$DIST_DIR"

# Keep the build environment after a failed attempt. This makes retries much
# faster because downloaded Python packages and appimagetool can be reused.
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip wheel
"$VENV/bin/python" -m pip install \
  -r "$ROOT/requirements.txt" \
  -r "$ROOT/requirements-build.txt"

rm -rf \
  "$BUILD_DIR/pyinstaller-dist" \
  "$BUILD_DIR/pyinstaller-work" \
  "$APPDIR"

"$VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --distpath "$BUILD_DIR/pyinstaller-dist" \
  --workpath "$BUILD_DIR/pyinstaller-work" \
  "$ROOT/packaging/appimage/PIA-Bazzite.spec"

mkdir -p \
  "$APPDIR/usr/lib/pia-bazzite" \
  "$APPDIR/usr/bin" \
  "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/512x512/apps" \
  "$APPDIR/usr/share/metainfo" \
  "$APPDIR/usr/share/doc/pia-bazzite"

cp -a \
  "$BUILD_DIR/pyinstaller-dist/PIA-Bazzite/." \
  "$APPDIR/usr/lib/pia-bazzite/"

cat > "$APPDIR/usr/bin/PIA-Bazzite" <<'EOF'
#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$HERE/lib/pia-bazzite/PIA-Bazzite" "$@"
EOF
chmod +x "$APPDIR/usr/bin/PIA-Bazzite"

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
set -e
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$APPDIR/usr/bin:$PATH"
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
exec "$APPDIR/usr/bin/PIA-Bazzite" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cp \
  "$ROOT/packaging/${APP_ID}.desktop" \
  "$APPDIR/${APP_ID}.desktop"
cp \
  "$ROOT/packaging/${APP_ID}.desktop" \
  "$APPDIR/usr/share/applications/${APP_ID}.desktop"
cp \
  "$ROOT/packaging/icons/512x512/apps/${APP_ID}.png" \
  "$APPDIR/${APP_ID}.png"
cp \
  "$ROOT/packaging/icons/512x512/apps/${APP_ID}.png" \
  "$APPDIR/usr/share/icons/hicolor/512x512/apps/${APP_ID}.png"
cp \
  "$ROOT/packaging/${APP_ID}.metainfo.xml" \
  "$APPDIR/usr/share/metainfo/${APP_ID}.metainfo.xml"
cp \
  "$ROOT/LICENSE" \
  "$ROOT/THIRD_PARTY_NOTICES.md" \
  "$APPDIR/usr/share/doc/pia-bazzite/"

ln -sfn "${APP_ID}.png" "$APPDIR/.DirIcon"

APPIMAGETOOL="${APPIMAGETOOL:-$BUILD_DIR/appimagetool-x86_64.AppImage}"
if [[ ! -x "$APPIMAGETOOL" ]]; then
  python3 - "$APPIMAGETOOL" <<'PY'
from pathlib import Path
import sys
from urllib.request import urlopen

destination = Path(sys.argv[1])
url = (
    "https://github.com/AppImage/appimagetool/releases/download/"
    "1.9.1/appimagetool-x86_64.AppImage"
)
with urlopen(url, timeout=180) as response:
    destination.write_bytes(response.read())
destination.chmod(0o755)
PY
fi

rm -f "$OUTPUT" "$OUTPUT.sha256"
ARCH="$ARCH" VERSION="$VERSION" APPIMAGE_EXTRACT_AND_RUN=1 \
  "$APPIMAGETOOL" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

sha256sum "$OUTPUT" > "$OUTPUT.sha256"
echo "Built: $OUTPUT"
echo "Checksum: $OUTPUT.sha256"
