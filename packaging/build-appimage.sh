#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-$(python3 -c 'from pia_bazzite import __version__; print(__version__)')}"
APP_ID="io.github.adventurefan.PIABazzite"
ARCH="x86_64"
BUILD_MODE="${PIA_BAZZITE_BUILD_MODE:-development}"
SOURCE_COMMIT="${PIA_BAZZITE_SOURCE_COMMIT:-}"
APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
BUILD_DIR="$ROOT/build/appimage"
VENV="$BUILD_DIR/venv"
APPDIR="$BUILD_DIR/PIA-Bazzite.AppDir"
DIST_DIR="$ROOT/dist"
OUTPUT="$DIST_DIR/PIA-Bazzite-${VERSION}-${ARCH}.AppImage"

mkdir -p "$BUILD_DIR" "$DIST_DIR"

if [[ "$BUILD_MODE" == "release" ]]; then
  if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]; then
      echo "ERROR: release mode requires a completely clean Git working tree." >&2
      git -C "$ROOT" status --short >&2
      exit 1
    fi
    HEAD_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
    if [[ -n "$SOURCE_COMMIT" && "$SOURCE_COMMIT" != "$HEAD_COMMIT" ]]; then
      echo "ERROR: requested release source commit does not match checked-out HEAD." >&2
      exit 1
    fi
    SOURCE_COMMIT="$HEAD_COMMIT"
  elif [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-fA-F]{40,64}$ ]]; then
    echo "ERROR: release mode without Git metadata requires an exact hexadecimal source commit." >&2
    exit 1
  fi
elif [[ "$BUILD_MODE" != "development" ]]; then
  echo "ERROR: PIA_BAZZITE_BUILD_MODE must be 'development' or 'release'." >&2
  exit 1
fi

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
  "$APPDIR/usr/share/doc/pia-bazzite" \
  "$APPDIR/usr/share/pia-bazzite"

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
export PIA_BAZZITE_HELPER_BUNDLE="$APPDIR/usr/share/pia-bazzite/kill-switch-helper-bundle"
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
# appimagetool 1.9.1 still looks for the older .appdata.xml basename while
# modern AppStream consumers use .metainfo.xml. Ship the same metadata under
# both accepted basenames so validation does not report a false missing-metadata warning.
cp \
  "$ROOT/packaging/${APP_ID}.metainfo.xml" \
  "$APPDIR/usr/share/metainfo/${APP_ID}.appdata.xml"
cp \
  "$ROOT/LICENSE" \
  "$ROOT/THIRD_PARTY_NOTICES.md" \
  "$APPDIR/usr/share/doc/pia-bazzite/"

THIRD_PARTY_DIR="$APPDIR/usr/share/doc/pia-bazzite/third-party-python"
"$VENV/bin/python" "$ROOT/packaging/collect_third_party_licenses.py" \
  --destination "$THIRD_PARTY_DIR"

# PySide6-Essentials 6.11.1 does not declare distributable open-source license
# files through its wheel metadata on every platform/build.  Do not silently
# treat that as "no license text required": ship pinned canonical GNU texts
# for the open-source license alternatives declared by the PyPI package.
PYSIDE_LICENSE_DIR="$THIRD_PARTY_DIR/PySide6-Qt"
mkdir -p "$PYSIDE_LICENSE_DIR"
verify_vendored_license() {
  local expected="$1"
  local file="$2"
  printf '%s  %s\n' "$expected" "$file" | sha256sum --check --status
}
verify_vendored_license \
  "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118" \
  "$ROOT/packaging/licenses/LGPL-3.0.txt" || { echo 'ERROR: vendored LGPL-3.0 text failed SHA-256 verification.' >&2; exit 1; }
verify_vendored_license \
  "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986" \
  "$ROOT/packaging/licenses/GPL-3.0.txt" || { echo 'ERROR: vendored GPL-3.0 text failed SHA-256 verification.' >&2; exit 1; }
verify_vendored_license \
  "edaef632cbb643e4e7a221717a6c441a4c1a7c918e6e4d56debc3d8739b233f6" \
  "$ROOT/packaging/licenses/GPL-2.0.txt" || { echo 'ERROR: vendored GPL-2.0 text failed SHA-256 verification.' >&2; exit 1; }
cp \
  "$ROOT/packaging/licenses/LGPL-3.0.txt" \
  "$ROOT/packaging/licenses/GPL-3.0.txt" \
  "$ROOT/packaging/licenses/GPL-2.0.txt" \
  "$PYSIDE_LICENSE_DIR/"
cat > "$PYSIDE_LICENSE_DIR/README.txt" <<'EOF_PYSIDE_LICENSE'
PySide6/Qt licensing notice for the bundled runtime

The PySide6-Essentials package metadata used by PIA Bazzite declares the
open-source alternatives LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only.
The canonical GNU LGPLv3, GPLv3 and GPLv2 texts are bundled here so the
AppImage does not depend on whether a particular wheel exposes license files
through Python package metadata.  Any license/notice files that the installed
wheel does expose are also copied by the generated third-party collector.

See THIRD_PARTY_NOTICES.md and the per-package PACKAGE_METADATA.txt files for
component/version metadata.
EOF_PYSIDE_LICENSE
chmod 0644 "$PYSIDE_LICENSE_DIR"/*

if [[ -z "$SOURCE_COMMIT" ]]; then
  if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]; then
      SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
    else
      SOURCE_COMMIT="working-tree"
    fi
  else
    SOURCE_COMMIT="unknown"
  fi
fi
cat > "$APPDIR/usr/share/doc/pia-bazzite/BUILD_INFO.txt" <<EOF
PIA Bazzite version: $VERSION
Build mode: $BUILD_MODE
Source commit: $SOURCE_COMMIT
EOF

"$VENV/bin/python" "$ROOT/packaging/build-helper-bundle.py" \
  --root "$ROOT" \
  --destination "$APPDIR/usr/share/pia-bazzite/kill-switch-helper-bundle" \
  --version "$VERSION"

ln -sfn "${APP_ID}.png" "$APPDIR/.DirIcon"

APPIMAGETOOL="${APPIMAGETOOL:-$BUILD_DIR/appimagetool-x86_64.AppImage}"

verify_appimagetool() {
  [[ -f "$APPIMAGETOOL" ]] || return 1
  printf '%s  %s\n' "$APPIMAGETOOL_SHA256" "$APPIMAGETOOL" | sha256sum --check --status
}

if [[ -e "$APPIMAGETOOL" ]] && ! verify_appimagetool; then
  echo "Cached appimagetool failed the pinned SHA-256 check; removing it before a fresh download."
  rm -f "$APPIMAGETOOL"
fi

if [[ ! -f "$APPIMAGETOOL" ]]; then
  DOWNLOAD_TMP="$(mktemp "$BUILD_DIR/.appimagetool-download.XXXXXX")"
  trap 'rm -f "${DOWNLOAD_TMP:-}"' EXIT
  python3 - "$APPIMAGETOOL_URL" "$DOWNLOAD_TMP" <<'PY_DOWNLOAD'
from pathlib import Path
import sys
from urllib.request import urlopen

url = sys.argv[1]
destination = Path(sys.argv[2])
with urlopen(url, timeout=180) as response:
    destination.write_bytes(response.read())
PY_DOWNLOAD
  printf '%s  %s\n' "$APPIMAGETOOL_SHA256" "$DOWNLOAD_TMP" | sha256sum --check --status || {
    echo "ERROR: downloaded appimagetool does not match the pinned SHA-256." >&2
    exit 1
  }
  chmod 0755 "$DOWNLOAD_TMP"
  mv -f "$DOWNLOAD_TMP" "$APPIMAGETOOL"
  trap - EXIT
fi

if ! verify_appimagetool; then
  echo "ERROR: appimagetool failed the pinned SHA-256 check." >&2
  exit 1
fi

rm -f "$OUTPUT" "$OUTPUT.sha256"
ARCH="$ARCH" VERSION="$VERSION" APPIMAGE_EXTRACT_AND_RUN=1 \
  "$APPIMAGETOOL" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

(
  cd "$DIST_DIR"
  sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256"
)
echo "Built: $OUTPUT"
echo "Checksum: $OUTPUT.sha256"
