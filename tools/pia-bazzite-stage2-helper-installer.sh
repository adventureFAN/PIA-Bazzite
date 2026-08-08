#!/usr/bin/env bash
set -euo pipefail
umask 022

TARGET_DIR="/usr/local/libexec/pia-bazzite"
TARGET_LAUNCHER="$TARGET_DIR/pia-bazzite-kill-switch-helper"
TARGET_SESSION_LAUNCHER="$TARGET_DIR/pia-bazzite-kill-switch-session"
TARGET_PACKAGE="$TARGET_DIR/pia_bazzite_kill_switch_helper"
TARGET_MANIFEST="$TARGET_DIR/kill-switch-helper-manifest.json"

SOURCE_FILES=(
  "helper/pia-bazzite-kill-switch-helper-installed"
  "helper/pia-bazzite-kill-switch-session-installed"
  "helper/pia_bazzite_kill_switch_helper/__init__.py"
  "helper/pia_bazzite_kill_switch_helper/cli.py"
  "helper/pia_bazzite_kill_switch_helper/core.py"
  "helper/pia_bazzite_kill_switch_helper/runner.py"
  "helper/pia_bazzite_kill_switch_helper/protocol.py"
  "helper/pia_bazzite_kill_switch_helper/installed_entry.py"
  "helper/pia_bazzite_kill_switch_helper/session_entry.py"
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

acquire_lock() {
  /usr/bin/install -d -o root -g root -m 0755 /run/lock
  exec 9>/run/lock/pia-bazzite-stage2-helper-installer.lock
  /usr/bin/flock -n 9 || fail "Another helper installation operation is already running."
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
  local path="$1" require_root_owner="${2:-no}"
  [ -f "$path" ] || fail "Source file is missing: $path"
  [ ! -L "$path" ] || fail "Source file must not be a symbolic link: $path"
  [ "$(stat -c '%h' -- "$path")" -eq 1 ] || fail "Source file has multiple hard links: $path"
  if [ "$require_root_owner" = yes ]; then
    [ "$(stat -c '%u:%g' -- "$path")" = "0:0" ] \
      || fail "Packaged source is not owned by root:root: $path"
  fi
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

verify_packaged_source() {
  local root="$1" expected_digest="$2" actual_digest mode
  [[ "$expected_digest" =~ ^[0-9a-f]{64}$ ]] || fail "Trusted packaged manifest digest is invalid."
  [[ "$root" == /run/pia-bazzite-helper-root-* ]] \
    || fail "Packaged helper source is outside the root-owned /run staging namespace."
  check_safe_directory "$root"
  mode="$(stat -c '%a' -- "$root")"
  [ "$mode" = 700 ] || fail "Packaged helper staging root must have mode 0700."

  check_source_file "$root/bundle-manifest.json" yes
  [ "$(stat -c '%a' -- "$root/bundle-manifest.json")" = 644 ] \
    || fail "Packaged helper manifest must have mode 0644."
  actual_digest="$(sha256sum -- "$root/bundle-manifest.json" | awk '{print $1}')"
  [ "$actual_digest" = "$expected_digest" ] \
    || fail "Packaged helper manifest does not match the trusted AppImage digest."

  /usr/bin/python3 -I - "$root" "$expected_digest" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import sys

root = Path(sys.argv[1]).resolve(strict=True)
trusted_digest = sys.argv[2]
manifest_path = root / "bundle-manifest.json"
if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != trusted_digest:
    raise SystemExit("ERROR: Packaged helper manifest digest changed during privileged validation.")
document = json.loads(manifest_path.read_text(encoding="utf-8"))
required = {"schema_version", "app_version", "helper_stage", "protocol_version", "files"}
if not isinstance(document, dict) or set(document) != required:
    raise SystemExit("ERROR: Packaged helper bundle manifest shape is invalid.")
if document.get("schema_version") != 1 or document.get("helper_stage") != 5 or document.get("protocol_version") != 1:
    raise SystemExit("ERROR: Packaged helper bundle compatibility metadata is invalid.")
if not isinstance(document.get("app_version"), str) or not document["app_version"]:
    raise SystemExit("ERROR: Packaged helper bundle app version is invalid.")
files = document.get("files")
expected = {
    "tools/pia-bazzite-stage2-helper-installer.sh": 0o755,
    "helper/pia-bazzite-kill-switch-helper-installed": 0o755,
    "helper/pia-bazzite-kill-switch-session-installed": 0o755,
    "helper/pia_bazzite_kill_switch_helper/__init__.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/cli.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/core.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/runner.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/protocol.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/installed_entry.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/session_entry.py": 0o644,
}
if not isinstance(files, dict) or set(files) != set(expected):
    raise SystemExit("ERROR: Packaged helper bundle file list is invalid.")
for relative, expected_mode in expected.items():
    path = root / relative
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SystemExit(f"ERROR: Unsafe packaged helper source: {relative}")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise SystemExit(f"ERROR: Packaged helper source is not root-owned: {relative}")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise SystemExit(f"ERROR: Wrong packaged helper source mode: {relative}")
    expected_hash = files.get(relative)
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise SystemExit(f"ERROR: Invalid packaged helper source checksum: {relative}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise SystemExit(f"ERROR: Packaged helper source checksum mismatch: {relative}")
PY
}

install_helper() {
  local mode="${1:-source}" trusted_digest="${2:-}" root temporary source relative source_hash target_hash session_hash require_root_source=no
  root="$(project_root)"

  case "$mode" in
    source)
      if [ -e "$root/bundle-manifest.json" ] || [ -L "$root/bundle-manifest.json" ]; then
        fail "Source-tree install refuses packaged bundle metadata; downgrade to source mode is forbidden."
      fi
      ;;
    packaged)
      require_root_source=yes
      verify_packaged_source "$root" "$trusted_digest"
      ;;
    *) fail "Invalid helper installation mode." ;;
  esac

  for relative in "${SOURCE_FILES[@]}"; do
    check_source_file "$root/$relative" "$require_root_source"
  done

  /usr/bin/python3 -I - "$root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for relative in (
    "helper/pia-bazzite-kill-switch-helper-installed",
    "helper/pia-bazzite-kill-switch-session-installed",
    "helper/pia_bazzite_kill_switch_helper/__init__.py",
    "helper/pia_bazzite_kill_switch_helper/cli.py",
    "helper/pia_bazzite_kill_switch_helper/core.py",
    "helper/pia_bazzite_kill_switch_helper/runner.py",
    "helper/pia_bazzite_kill_switch_helper/protocol.py",
    "helper/pia_bazzite_kill_switch_helper/installed_entry.py",
    "helper/pia_bazzite_kill_switch_helper/session_entry.py",
):
    source = root / relative
    compile(source.read_text(encoding="utf-8"), str(source), "exec")
PY

  ensure_directories
  check_existing_target_file "$TARGET_LAUNCHER"
  check_existing_target_file "$TARGET_SESSION_LAUNCHER"
  check_existing_target_file "$TARGET_MANIFEST"
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py session_entry.py; do
    check_existing_target_file "$TARGET_PACKAGE/$relative"
  done

  temporary="$TARGET_DIR/.pia-bazzite-kill-switch-helper.$$"
  trap 'rm -f -- "$temporary" "$TARGET_DIR/.kill-switch-helper-manifest.$$"' EXIT
  /usr/bin/install -o root -g root -m 0755 \
    -- "$root/helper/pia-bazzite-kill-switch-helper-installed" "$temporary"
  /usr/bin/mv -fT -- "$temporary" "$TARGET_LAUNCHER"

  temporary="$TARGET_DIR/.pia-bazzite-kill-switch-session.$$"
  /usr/bin/install -o root -g root -m 0755 \
    -- "$root/helper/pia-bazzite-kill-switch-session-installed" "$temporary"
  /usr/bin/mv -fT -- "$temporary" "$TARGET_SESSION_LAUNCHER"

  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py session_entry.py; do
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
    "pia-bazzite-kill-switch-session",
    "pia_bazzite_kill_switch_helper/__init__.py",
    "pia_bazzite_kill_switch_helper/cli.py",
    "pia_bazzite_kill_switch_helper/core.py",
    "pia_bazzite_kill_switch_helper/runner.py",
    "pia_bazzite_kill_switch_helper/protocol.py",
    "pia_bazzite_kill_switch_helper/installed_entry.py",
    "pia_bazzite_kill_switch_helper/session_entry.py",
)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

payload = {
    "schema_version": 1,
    "install_format": 1,
    "helper_stage": 5,
    "protocol_version": 1,
    "files": {name: sha256(root / name) for name in relative_files},
}
temporary = manifest.with_name(f".{manifest.name}.{os.getpid()}")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chown(temporary, 0, 0)
os.chmod(temporary, 0o644)
os.replace(temporary, manifest)
PY

  /usr/bin/chown root:root -- "$TARGET_LAUNCHER" "$TARGET_SESSION_LAUNCHER" "$TARGET_MANIFEST" "$TARGET_PACKAGE"/*.py
  /usr/bin/chmod 0755 -- "$TARGET_LAUNCHER" "$TARGET_SESSION_LAUNCHER"
  /usr/bin/chmod 0644 -- "$TARGET_MANIFEST" "$TARGET_PACKAGE"/*.py

  [ "$(stat -c '%u:%g:%a' -- "$TARGET_LAUNCHER")" = "0:0:755" ] \
    || fail "Installed launcher ownership or mode is incorrect."
  [ "$(stat -c '%u:%g:%a' -- "$TARGET_SESSION_LAUNCHER")" = "0:0:755" ] \
    || fail "Installed session launcher ownership or mode is incorrect."
  [ "$(stat -c '%u:%g:%a' -- "$TARGET_MANIFEST")" = "0:0:644" ] \
    || fail "Installed manifest ownership or mode is incorrect."
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py session_entry.py; do
    [ "$(stat -c '%u:%g:%a' -- "$TARGET_PACKAGE/$relative")" = "0:0:644" ] \
      || fail "Installed module ownership or mode is incorrect: $relative"
  done

  source_hash="$(sha256sum -- "$root/helper/pia-bazzite-kill-switch-helper-installed" | awk '{print $1}')"
  target_hash="$(sha256sum -- "$TARGET_LAUNCHER" | awk '{print $1}')"
  [ "$source_hash" = "$target_hash" ] || fail "Installed launcher checksum mismatch."
  source_hash="$(sha256sum -- "$root/helper/pia-bazzite-kill-switch-session-installed" | awk '{print $1}')"
  session_hash="$(sha256sum -- "$TARGET_SESSION_LAUNCHER" | awk '{print $1}')"
  [ "$source_hash" = "$session_hash" ] || fail "Installed session launcher checksum mismatch."

  trap - EXIT
  printf 'Installed helper: %s\n' "$TARGET_LAUNCHER"
  printf 'Installed session: %s\n' "$TARGET_SESSION_LAUNCHER"
  printf 'Installed package: %s\n' "$TARGET_PACKAGE"
  printf 'Installed manifest: %s\n' "$TARGET_MANIFEST"
  stat -c 'Launcher owner: %U:%G  Mode: %a  Size: %s bytes' -- "$TARGET_LAUNCHER"
  printf 'Launcher SHA-256: %s\n' "$target_hash"
  printf 'Session SHA-256: %s\n' "$session_hash"
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

preflight_uninstall_file() {
  local path="$1"
  if [ -L "$path" ]; then
    fail "Refusing symbolic-link target before uninstall: $path"
  elif [ -e "$path" ]; then
    [ -f "$path" ] || fail "Refusing non-regular target before uninstall: $path"
    [ "$(stat -c '%u:%g' -- "$path")" = "0:0" ] \
      || fail "Refusing target not owned by root:root before uninstall: $path"
  fi
}

preflight_uninstall() {
  local relative
  preflight_uninstall_file "$TARGET_LAUNCHER"
  preflight_uninstall_file "$TARGET_SESSION_LAUNCHER"
  preflight_uninstall_file "$TARGET_MANIFEST"
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py session_entry.py; do
    preflight_uninstall_file "$TARGET_PACKAGE/$relative"
  done
}

uninstall_helper() {
  local relative
  preflight_uninstall
  remove_regular_root_file "$TARGET_LAUNCHER"
  remove_regular_root_file "$TARGET_SESSION_LAUNCHER"
  remove_regular_root_file "$TARGET_MANIFEST"
  for relative in __init__.py cli.py core.py runner.py protocol.py installed_entry.py session_entry.py; do
    remove_regular_root_file "$TARGET_PACKAGE/$relative"
  done
  /usr/bin/rmdir --ignore-fail-on-non-empty "$TARGET_PACKAGE" 2>/dev/null || true
  /usr/bin/rmdir --ignore-fail-on-non-empty "$TARGET_DIR" 2>/dev/null || true
  printf 'Kill-switch helper installation is absent.\n'
}

show_status() {
  local missing=0 relative
  for relative in \
    "$TARGET_LAUNCHER" \
    "$TARGET_SESSION_LAUNCHER" \
    "$TARGET_MANIFEST" \
    "$TARGET_PACKAGE/__init__.py" \
    "$TARGET_PACKAGE/cli.py" \
    "$TARGET_PACKAGE/core.py" \
    "$TARGET_PACKAGE/runner.py" \
    "$TARGET_PACKAGE/protocol.py" \
    "$TARGET_PACKAGE/installed_entry.py" \
    "$TARGET_PACKAGE/session_entry.py"
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
acquire_lock
case "${1:-}" in
  install) install_helper source ;;
  install-packaged) install_helper packaged "${2:-}" ;;
  uninstall) uninstall_helper ;;
  status) show_status ;;
  *) fail "Usage: $0 {install|install-packaged SHA256|uninstall|status}" ;;
esac
