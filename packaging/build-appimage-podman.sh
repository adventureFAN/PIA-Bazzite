#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_MODE="${PIA_BAZZITE_BUILD_MODE:-development}"
SOURCE_COMMIT="working-tree"

if ! command -v podman >/dev/null 2>&1; then
  echo "Podman was not found."
  echo "Build through the GitHub Actions release workflow instead."
  exit 1
fi

# Never relabel the live checkout for a rootless Podman build.  Earlier
# development/host tests may legitimately leave root-owned transient files
# (for example Python bytecode created by a privileged probe).  A :Z bind
# mount of the complete checkout would make Podman try to set SELinux labels
# on those files before the container starts and can therefore fail even
# though the files are not part of the release payload.
#
# Build from a fresh user-owned staging copy instead.  Besides avoiding that
# SELinux ownership trap this gives the local release build the same useful
# property as CI: caches, test results and other workstation artefacts cannot
# silently become build inputs.
STAGE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pia-bazzite-appimage-build.XXXXXX")"
WORKSPACE="$STAGE_ROOT/workspace"
mkdir -p "$WORKSPACE"

cleanup() {
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

if [[ "$BUILD_MODE" == "release" ]]; then
  if ! command -v git >/dev/null 2>&1 || ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: release mode requires a Git checkout." >&2
    exit 1
  fi
  if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]; then
    echo "ERROR: release mode requires a completely clean Git working tree, including no untracked files." >&2
    git -C "$ROOT" status --short >&2
    exit 1
  fi
  SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
  git -C "$ROOT" archive --format=tar HEAD | tar -C "$WORKSPACE" -xf -
elif [[ "$BUILD_MODE" == "development" ]]; then
  (
    cd "$ROOT"
    tar \
      --exclude='./.git' \
      --exclude='./.venv' \
      --exclude='./build' \
      --exclude='./dist' \
      --exclude='./test-results' \
      --exclude='*/__pycache__' \
      --exclude='*.pyc' \
      --exclude='*.pyo' \
      -cf - .
  ) | tar -C "$WORKSPACE" -xf -
else
  echo "ERROR: PIA_BAZZITE_BUILD_MODE must be 'development' or 'release'." >&2
  exit 1
fi

echo "Building PIA Bazzite in an Ubuntu 22.04 container from a clean $BUILD_MODE source snapshot ..."

podman run --rm \
  -e HOME=/tmp/pia-build-home \
  -e PIA_BAZZITE_BUILD_MODE="$BUILD_MODE" \
  -e PIA_BAZZITE_SOURCE_COMMIT="$SOURCE_COMMIT" \
  -v "$WORKSPACE:/workspace:Z" \
  -w /workspace \
  docker.io/library/ubuntu:22.04 \
  bash -lc '
    set -euo pipefail

    mkdir -p "$HOME"
    export DEBIAN_FRONTEND=noninteractive

    apt-get update
    apt-get install -y --no-install-recommends \
      binutils \
      ca-certificates \
      file \
      libdbus-1-3 \
      libegl1 \
      libfontconfig1 \
      libgl1 \
      libglib2.0-0 \
      libice6 \
      libnss3 \
      libopengl0 \
      libpython3.10 \
      libsm6 \
      libx11-6 \
      libx11-xcb1 \
      libxcb1 \
      libxcb-cursor0 \
      libxcb-icccm4 \
      libxcb-image0 \
      libxcb-keysyms1 \
      libxcb-randr0 \
      libxcb-render-util0 \
      libxcb-shape0 \
      libxcb-shm0 \
      libxcb-sync1 \
      libxcb-util1 \
      libxcb-xfixes0 \
      libxcb-xinerama0 \
      libxcb-xkb1 \
      libxext6 \
      libxkbcommon0 \
      libxkbcommon-x11-0 \
      libxrender1 \
      python3 \
      python3-pip \
      python3-venv

    if ! command -v objdump >/dev/null 2>&1; then
      echo "ERROR: objdump is missing after package installation."
      exit 1
    fi

    if ! ldconfig -p | grep -q "libpython3.10.so.1.0"; then
      echo "ERROR: libpython3.10.so.1.0 is missing after package installation."
      exit 1
    fi

    ./packaging/build-appimage.sh
  '

if [[ ! -d "$WORKSPACE/dist" ]]; then
  echo "ERROR: container build completed without a dist directory."
  exit 1
fi

mkdir -p "$ROOT/dist"
shopt -s nullglob
ARTIFACTS=("$WORKSPACE"/dist/PIA-Bazzite-*-x86_64.AppImage "$WORKSPACE"/dist/PIA-Bazzite-*-x86_64.AppImage.sha256)
shopt -u nullglob
if [[ ${#ARTIFACTS[@]} -ne 2 ]]; then
  echo "ERROR: expected exactly one AppImage and one SHA-256 sidecar in the staged dist directory."
  printf 'Found: %s\n' "${ARTIFACTS[*]:-(none)}"
  exit 1
fi

for artifact in "${ARTIFACTS[@]}"; do
  cp -f "$artifact" "$ROOT/dist/$(basename "$artifact")"
done

echo
echo "Finished. The AppImage is in:"
echo "$ROOT/dist/"
