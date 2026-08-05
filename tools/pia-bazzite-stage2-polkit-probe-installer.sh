#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="/usr/local/libexec/pia-bazzite"
TARGET="$TARGET_DIR/pia-bazzite-auth-probe"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [ "$(id -u)" -eq 0 ] || fail "Run this installer with sudo."
}

project_root() {
  local script_path
  script_path="$(readlink -f -- "$0")"
  dirname "$(dirname "$script_path")"
}

check_safe_directory() {
  local path="$1"
  [ -d "$path" ] || fail "Not a directory: $path"
  [ ! -L "$path" ] || fail "Refusing symbolic-link directory: $path"
  [ "$(stat -c '%u:%g' -- "$path")" = "0:0" ] || fail "Directory is not owned by root:root: $path"
  local mode
  mode="$(stat -c '%a' -- "$path")"
  if [ $((8#$mode & 8#022)) -ne 0 ]; then
    fail "Directory is group- or world-writable: $path"
  fi
}

install_probe() {
  local root source temporary source_hash target_hash
  root="$(project_root)"
  source="$root/helper/pia-bazzite-polkit-probe"

  [ -f "$source" ] || fail "Probe source is missing: $source"
  [ ! -L "$source" ] || fail "Probe source must not be a symbolic link."
  /usr/bin/python3 -m py_compile "$source"

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

  if [ -L "$TARGET" ]; then
    fail "Refusing to replace a symbolic-link target: $TARGET"
  elif [ -e "$TARGET" ]; then
    [ -f "$TARGET" ] || fail "Refusing to replace a non-regular target: $TARGET"
    [ "$(stat -c '%u:%g' -- "$TARGET")" = "0:0" ] || fail "Refusing to replace a target not owned by root:root."
  fi

  temporary="$TARGET_DIR/.pia-bazzite-auth-probe.$$"
  trap 'rm -f -- "$temporary"' EXIT
  /usr/bin/install -o root -g root -m 0755 -- "$source" "$temporary"
  /usr/bin/chown root:root -- "$temporary"
  /usr/bin/chmod 0755 -- "$temporary"
  /usr/bin/mv -fT -- "$temporary" "$TARGET"
  trap - EXIT

  [ -f "$TARGET" ] || fail "Installed target is missing."
  [ ! -L "$TARGET" ] || fail "Installed target became a symbolic link."
  [ "$(stat -c '%u:%g' -- "$TARGET")" = "0:0" ] || fail "Installed target is not owned by root:root."
  [ "$(stat -c '%a' -- "$TARGET")" = "755" ] || fail "Installed target mode is not 0755."

  source_hash="$(sha256sum -- "$source" | awk '{print $1}')"
  target_hash="$(sha256sum -- "$TARGET" | awk '{print $1}')"
  [ "$source_hash" = "$target_hash" ] || fail "Installed probe checksum mismatch."

  printf 'Installed: %s\n' "$TARGET"
  stat -c 'Owner: %U:%G  Mode: %a  Size: %s bytes' -- "$TARGET"
  printf 'SHA-256: %s\n' "$target_hash"
}

uninstall_probe() {
  if [ -L "$TARGET" ]; then
    fail "Refusing to remove a symbolic-link target: $TARGET"
  fi
  if [ -e "$TARGET" ]; then
    [ -f "$TARGET" ] || fail "Refusing to remove a non-regular target: $TARGET"
    [ "$(stat -c '%u:%g' -- "$TARGET")" = "0:0" ] || fail "Refusing to remove a target not owned by root:root."
    /usr/bin/rm -f -- "$TARGET"
    printf 'Removed: %s\n' "$TARGET"
  else
    printf 'Already absent: %s\n' "$TARGET"
  fi
  /usr/bin/rmdir --ignore-fail-on-non-empty "$TARGET_DIR" 2>/dev/null || true
}

show_status() {
  if [ -e "$TARGET" ]; then
    [ ! -L "$TARGET" ] || fail "Installed target is a symbolic link."
    stat -c 'Installed: %n' -- "$TARGET"
    stat -c 'Owner: %U:%G' -- "$TARGET"
    stat -c 'Mode: %a' -- "$TARGET"
    stat -c 'Size: %s bytes' -- "$TARGET"
    sha256sum -- "$TARGET"
  else
    printf 'Not installed: %s\n' "$TARGET"
  fi
}

require_root
case "${1:-}" in
  install) install_probe ;;
  uninstall) uninstall_probe ;;
  status) show_status ;;
  *) fail "Usage: $0 {install|uninstall|status}" ;;
esac
