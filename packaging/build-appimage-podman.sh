#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v podman >/dev/null 2>&1; then
  echo "Podman was not found."
  echo "Build through the GitHub Actions release workflow instead."
  exit 1
fi

echo "Building PIA Bazzite in an Ubuntu 22.04 container ..."

podman run --rm \
  -e HOME=/tmp/pia-build-home \
  -v "$ROOT:/workspace:Z" \
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

echo
echo "Finished. The AppImage is in:"
echo "$ROOT/dist/"
