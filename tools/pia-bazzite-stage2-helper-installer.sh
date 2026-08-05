#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="/usr/local/libexec/pia-bazzite"
TARGET_LAUNCHER="$TARGET_DIR/pia-bazzite-kill-switch-helper"
TARGET_PACKAGE="$TARGET_DIR/pia_bazzite_kill_switch_helper"
TARGET_MANIFEST="$TARGET_DIR/kill-switch-helper-manifest.json"

SOURCE_FILES=(
  "helper/pia-bazzite-kill-switch-helper-installed"
  "helper/pia_bazzite_kill_switch_helper/__init__.py"
  "helper/pia_bazzite_kill_switch_helper/cli.py"
  "helper/pia_bazzite_kill_switch_helper/core.py"
  "helper/pia_bazzite_kill_switch_helper/runner.py"
  "helper/pia_bazzite_kill_switch_helper/protocol.py"
  "helper/pia_bazzite_kill_switch_helper/installed_entry.py"
)

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

project_root() {
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P
}

require_root() {
  [ "${EUID:-$(id -u)}" -eq 0 ] || fail "This installer must run as root."
}

check_safe_directory() {
  local path="$1" mode
  [ -d "$path" ] || fail "Not a directory: $path"
  [ ! -L "$path" ] || fail "Refusing symbolic-link directory: $path"
  [ "$(stat -c '%u:%g' -- "$path")" = "0:0" ] \
    || fail "Directory is not owned by root:root: $path"
  mode="$(stat -c '%a' -- "$path")"
  if [ $((8#$mode & 8#022)) -ne 0 ]; then
    fail "Directory is group- or world-writable: $path"
  fi
}

check_source_file() {
  local path="$1"
  [ -f "$path" ] || fail "Source file is missing: $path"
  [ ! -L "$path" ] || fail "Source file must not be a symbolic link: $path"
  [ "$(stat -c '%h' -- "$path")" -eq 1 ] || fail "Source file has multiple hard links: $path"
}

check_existing_target_file() {
  local path="$1"
  if [ -L "$path" ]; then
    fail "Refusing symbolic-link target: $path"
  elif [ -e "$path" ]; then
    [ -f "$path" ] || fail "Refusing non-regular target: $path"
    [ "$(stat -c '%u:%g' -- "$path")" = "0:0" ] \
      || fail "Refusing target not owned by root:root: $path"
  fi
}

ensure_directories() {
  if [ -L /usr/local/libexec ]; then
    fail "Refusing symbolic-link directory: /usr/local/libexec"
  elif [ -e /usr/local/libexec ]; then
    check_safe_directory /usr/local/libexec
  else
    /usr/bin/install -d -o root -g root -m 0755 /usr/local/libexec
    check_safe_directory /usr/local/libexec
  fi

  if [ -L "$TARGET_DIR" ]; then
    fail "Refusing symbolic-link directory: $TARGET_DIR"
  elif [ -e "$TARGET_DIR" ]; then
    check_safe_directory "$TARGET_DIR"
  else
    /usr/bin/install -d -o root -g root -m 0755 "$TARGET_DIR"
    check_safe_directory "$TARGET_DIR"
  fi

  if [ -L "$TARGET_PACKAGE" ]; then
    fail "Refusing symbolic-link directory: $TARGET_PACKAGE"
  elif [ -e "$TARGET_PACKAGE" ]; then
    check_safe_directory "$TARGET_PACKAGE"
  else
    /usr/bin/install -d -o root -g root -m 0755 "$TARGET_PACKAGE"
    check_safe_directory "$TARGET_PACKAGE"
  fi
}

install_helper() {
  local root temporary source relative target source_hash target_hash
  root="$(project_root)"

  for relative in "${SOURCE_FILES[@]}"; do
    check_source_file "$root/$relative"
  done

  /usr/bin/python3 -I - "$root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for relative in (
    "helper/pia-bazzite-kill-switch-helper-installed",
    "helper/pia_bazzite_kill_switch_helper/__init__.py",
    "helper/pia_bazzite_kill_switch_helper/cli.py",
    "helper/pia_bazzite_kill_switch_helper/core.py",
    "helper/pia_bazzite_kill_switch_helper/runner.py",
    "helper/pia_bazzite_kill_switch_helper/protocol.py",
    "helper/pia_bazzite_kill_switch_helper/installed_entry.py",
):
    source = root / relative
    compile(source.read_text(encoding="utf-8"), str(source), "exec")
PY

  ensure_directories
  check_existing_target_file "$TARGET_LAUNCHER"
  check_existing_target_file "$TARGET_MANIFEST"
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py; do
    check_existing_target_file "$TARGET_PACKAGE/$relative"
  done

  temporary="$TARGET_DIR/.pia-bazzite-kill-switch-helper.$$"
  trap 'rm -f -- "$temporary" "$TARGET_DIR/.kill-switch-helper-manifest.$$"' EXIT
  /usr/bin/install -o root -g root -m 0755 \
    -- "$root/helper/pia-bazzite-kill-switch-helper-installed" "$temporary"
  /usr/bin/mv -fT -- "$temporary" "$TARGET_LAUNCHER"

  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py; do
    source="$root/helper/pia_bazzite_kill_switch_helper/$relative"
    target="$TARGET_PACKAGE/$relative"
    temporary="$TARGET_PACKAGE/.$relative.$$"
    /usr/bin/install -o root -g root -m 0644 -- "$source" "$temporary"
    /usr/bin/mv -fT -- "$temporary" "$target"
  done

  /usr/bin/python3 -I - "$TARGET_DIR" "$TARGET_MANIFEST" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import sys

root = Path(sys.argv[1])
manifest = Path(sys.argv[2])
relative_files = (
    "pia-bazzite-kill-switch-helper",
    "pia_bazzite_kill_switch_helper/__init__.py",
    "pia_bazzite_kill_switch_helper/cli.py",
    "pia_bazzite_kill_switch_helper/core.py",
    "pia_bazzite_kill_switch_helper/runner.py",
    "pia_bazzite_kill_switch_helper/protocol.py",
    "pia_bazzite_kill_switch_helper/installed_entry.py",
)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

payload = {
    "schema_version": 1,
    "files": {name: sha256(root / name) for name in relative_files},
}
temporary = manifest.with_name(f".{manifest.name}.{os.getpid()}")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chown(temporary, 0, 0)
os.chmod(temporary, 0o644)
os.replace(temporary, manifest)
PY

  /usr/bin/chown root:root -- "$TARGET_LAUNCHER" "$TARGET_MANIFEST" "$TARGET_PACKAGE"/*.py
  /usr/bin/chmod 0755 -- "$TARGET_LAUNCHER"
  /usr/bin/chmod 0644 -- "$TARGET_MANIFEST" "$TARGET_PACKAGE"/*.py

  [ "$(stat -c '%u:%g:%a' -- "$TARGET_LAUNCHER")" = "0:0:755" ] \
    || fail "Installed launcher ownership or mode is incorrect."
  [ "$(stat -c '%u:%g:%a' -- "$TARGET_MANIFEST")" = "0:0:644" ] \
    || fail "Installed manifest ownership or mode is incorrect."
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py; do
    [ "$(stat -c '%u:%g:%a' -- "$TARGET_PACKAGE/$relative")" = "0:0:644" ] \
      || fail "Installed module ownership or mode is incorrect: $relative"
  done

  source_hash="$(sha256sum -- "$root/helper/pia-bazzite-kill-switch-helper-installed" | awk '{print $1}')"
  target_hash="$(sha256sum -- "$TARGET_LAUNCHER" | awk '{print $1}')"
  [ "$source_hash" = "$target_hash" ] || fail "Installed launcher checksum mismatch."

  trap - EXIT
  printf 'Installed helper: %s\n' "$TARGET_LAUNCHER"
  printf 'Installed package: %s\n' "$TARGET_PACKAGE"
  printf 'Installed manifest: %s\n' "$TARGET_MANIFEST"
  stat -c 'Launcher owner: %U:%G  Mode: %a  Size: %s bytes' -- "$TARGET_LAUNCHER"
  printf 'Launcher SHA-256: %s\n' "$target_hash"
}

remove_regular_root_file() {
  local path="$1"
  if [ -L "$path" ]; then
    fail "Refusing to remove symbolic-link target: $path"
  elif [ -e "$path" ]; then
    [ -f "$path" ] || fail "Refusing to remove non-regular target: $path"
    [ "$(stat -c '%u:%g' -- "$path")" = "0:0" ] \
      || fail "Refusing to remove target not owned by root:root: $path"
    /usr/bin/rm -f -- "$path"
    printf 'Removed: %s\n' "$path"
  fi
}

uninstall_helper() {
  local relative
  remove_regular_root_file "$TARGET_LAUNCHER"
  remove_regular_root_file "$TARGET_MANIFEST"
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py; do
    remove_regular_root_file "$TARGET_PACKAGE/$relative"
  done
  /usr/bin/rmdir --ignore-fail-on-non-empty "$TARGET_PACKAGE" 2>/dev/null || true
  /usr/bin/rmdir --ignore-fail-on-non-empty "$TARGET_DIR" 2>/dev/null || true
  printf 'Stage-2 helper installation is absent.\n'
}

show_status() {
  local missing=0 relative
  for relative in \
    "$TARGET_LAUNCHER" \
    "$TARGET_MANIFEST" \
    "$TARGET_PACKAGE/__init__.py" \
    "$TARGET_PACKAGE/cli.py" \
    "$TARGET_PACKAGE/core.py" \
    "$TARGET_PACKAGE/runner.py" \
    "$TARGET_PACKAGE/protocol.py" \
    "$TARGET_PACKAGE/installed_entry.py"
  do
    if [ -e "$relative" ]; then
      [ ! -L "$relative" ] || fail "Installed target is a symbolic link: $relative"
      stat -c '%U:%G %a %s %n' -- "$relative"
    else
      printf 'MISSING %s\n' "$relative"
      missing=1
    fi
  done
  return "$missing"
}

require_root
case "${1:-}" in
  install) install_helper ;;
  uninstall) uninstall_helper ;;
  status) show_status ;;
  *) fail "Usage: $0 {install|uninstall|status}" ;;
esac
