#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -c 'from pia_bazzite import __version__; print(__version__)')"
ARCH="x86_64"
APPIMAGE="$ROOT/dist/PIA-Bazzite-${VERSION}-${ARCH}.AppImage"
CHECKSUM="$APPIMAGE.sha256"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8b2-real-appimage-helper-host-test.txt"
EXTRACT_ROOT="$ROOT/build/stage8b2-appimage-extract"
BUNDLE="$EXTRACT_ROOT/squashfs-root/usr/share/pia-bazzite/kill-switch-helper-bundle"
SNAPSHOT_BEFORE="$ROOT/build/stage8b2-current-helper-before.json"
SNAPSHOT_AFTER="$ROOT/build/stage8b2-current-helper-after.json"
TABLE="pia_bazzite_killswitch"
RESET_UNIT="pia-bazzite-stage8b2-appimage-safety-reset"
RESET_DELAY="15min"
mkdir -p "$REPORT_DIR" "$ROOT/build"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite Stage-8B.2 real %s AppImage helper install/upgrade host test\n' "$VERSION"
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test builds the release-candidate AppImage, verifies its embedded helper bundle,\n'
printf 'proves that a normal AppImage FUSE bundle can be copied into the exact private staging\n'
printf 'path used for privilege handoff, then exercises missing/current/outdated helper handling\n'
printf 'without intentionally starting a VPN or firewall lock.\n\n'

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

APP_PID=""
SUDO_KEEPALIVE_PID=""
ORIGINAL_KS=""
HELPER_MUTATED=0
RESET_ARMED=0

stop_app() {
  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" >/dev/null 2>&1; then
    kill -TERM -- "-$APP_PID" >/dev/null 2>&1 || kill -TERM "$APP_PID" >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
      kill -0 "$APP_PID" >/dev/null 2>&1 || break
      sleep 0.1
    done
    if kill -0 "$APP_PID" >/dev/null 2>&1; then
      kill -KILL -- "-$APP_PID" >/dev/null 2>&1 || kill -KILL "$APP_PID" >/dev/null 2>&1 || true
    fi
    wait "$APP_PID" 2>/dev/null || true
  fi
  APP_PID=""
}

cancel_reset() {
  sudo systemctl stop "${RESET_UNIT}.timer" "${RESET_UNIT}.service" >/dev/null 2>&1 || true
  sudo systemctl reset-failed "${RESET_UNIT}.service" >/dev/null 2>&1 || true
  RESET_ARMED=0
}

restore_setting() {
  [[ -n "$ORIGINAL_KS" ]] || return 0
  STAGE8B2_ORIGINAL_KS="$ORIGINAL_KS" PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY' || true
import os
from pia_bazzite.settings import create_settings
s=create_settings()
s.setValue("kill_switch/enabled", os.environ["STAGE8B2_ORIGINAL_KS"] == "1")
s.sync()
PY
}

cleanup() {
  local status=$?
  stop_app
  restore_setting
  if [[ $status -ne 0 && $HELPER_MUTATED -eq 1 ]]; then
    printf '\nINFO    Test failed after helper mutation; attempting safe source-tree helper restoration.\n'
    if ! nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -Fxq 'PIA Bazzite:wireguard'; then
      if ! sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
        sudo bash "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" install || true
      else
        printf 'WARNING A production firewall lock exists; helper restoration was not attempted.\n'
      fi
    else
      printf 'WARNING PIA VPN is active; helper restoration was not attempted.\n'
    fi
  fi
  if [[ $status -eq 0 && $RESET_ARMED -eq 1 ]]; then
    cancel_reset
  fi
  if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
    kill "$SUDO_KEEPALIVE_PID" >/dev/null 2>&1 || true
    wait "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT

[[ -x "$ROOT/.venv/bin/python" ]] || fail '.venv/bin/python is missing. Run the normal project setup first.'
[[ -x /usr/bin/sudo ]] || fail '/usr/bin/sudo is missing.'
command -v podman >/dev/null 2>&1 || fail 'Podman is missing. Stage 8B.2 uses the release-equivalent Ubuntu 22.04 container build.'
command -v nmcli >/dev/null 2>&1 || fail 'nmcli is missing.'
command -v systemd-run >/dev/null 2>&1 || fail 'systemd-run is missing.'
command -v setsid >/dev/null 2>&1 || fail 'setsid is missing.'
if [[ -x /usr/sbin/nft ]]; then NFT_BIN=/usr/sbin/nft; elif [[ -x /usr/bin/nft ]]; then NFT_BIN=/usr/bin/nft; else fail 'nft is missing.'; fi

"$ROOT/.venv/bin/python" "$ROOT/tools/pia-bazzite-stage6c2-instance-preflight.py" \
  || fail 'Close every PIA Bazzite window and tray instance before Stage 8B.2.'
if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -Fxq 'PIA Bazzite:wireguard'; then
  fail 'PIA Bazzite is connected. Disconnect it before Stage 8B.2.'
fi
printf 'PASS    PIA Bazzite is disconnected before the AppImage helper test.\n'

ORIGINAL_KS="$(PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY'
from pia_bazzite.settings import bool_value, create_settings
print("1" if bool_value(create_settings(), "kill_switch/enabled", False) else "0")
PY
)"
printf 'INFO    Original Kill Switch preference recorded for restoration after the test.\n'

printf '\n--- Build real %s release-candidate AppImage ---\n' "$VERSION"
rm -f "$APPIMAGE" "$CHECKSUM"
bash "$ROOT/packaging/build-appimage-podman.sh"
[[ -x "$APPIMAGE" ]] || fail "Release-candidate AppImage was not built: $APPIMAGE"
[[ -f "$CHECKSUM" ]] || fail "Release-candidate checksum is missing: $CHECKSUM"
(
  cd "$ROOT/dist"
  sha256sum -c "$(basename "$CHECKSUM")"
) || fail 'The AppImage SHA-256 sidecar does not verify from the release directory.'
VERSION_OUTPUT="$(APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGE" --version)"
[[ "$VERSION_OUTPUT" == "PIA Bazzite $VERSION" ]] || fail "Unexpected AppImage version output: $VERSION_OUTPUT"
printf 'PASS    Built AppImage reports PIA Bazzite %s and its portable SHA-256 sidecar verifies.\n' "$VERSION"

printf '\n%s\n' '--- Independently inspect the embedded helper bundle ---'
rm -rf "$EXTRACT_ROOT"
mkdir -p "$EXTRACT_ROOT"
(
  cd "$EXTRACT_ROOT"
  "$APPIMAGE" --appimage-extract >/dev/null
)
[[ -d "$BUNDLE" ]] || fail 'The extracted AppImage does not contain the fixed helper bundle.'
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" bundle --bundle "$BUNDLE" >/dev/null
printf 'PASS    Extracted AppImage contains the exact %s helper payload and manifest.\n' "$VERSION"

printf '\n%s\n' '--- Root authorization and clean-host preflight ---'
sudo -v || fail 'sudo authorization failed.'
(
  while sleep 30; do sudo -n -v >/dev/null 2>&1 || exit 0; done
) &
SUDO_KEEPALIVE_PID=$!
if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
  fail 'A production Kill Switch firewall table already exists. Run the Stage-7D Emergency Reset first.'
fi
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" "$ROOT/tools/pia-bazzite-stage7b-record-preflight.py" \
  || fail 'A previous crash-recovery path exists. Run the Stage-7D Emergency Reset first.'
printf 'PASS    No VPN, firewall lock, or crash-recovery path is active.\n'

printf '\n%s\n' '--- Prove the normal AppImage bundle can be staged for root before changing the helper ---'
setsid env -u APPIMAGE_EXTRACT_AND_RUN "$APPIMAGE" &
APP_PID=$!
MOUNT_BUNDLE=""
for _ in $(seq 1 120); do
  if ! kill -0 "$APP_PID" >/dev/null 2>&1; then
    fail 'The normal AppImage process exited before its packaged bundle could be observed.'
  fi
  while read -r proc_pid proc_sid; do
    [[ "$proc_sid" == "$APP_PID" ]] || continue
    proc_environ="/proc/$proc_pid/environ"
    [[ -r "$proc_environ" ]] || continue
    value="$(
      { tr '\0' '\n' < "$proc_environ"; } 2>/dev/null \
        | sed -n 's/^PIA_BAZZITE_HELPER_BUNDLE=//p' \
        | head -n1 \
        || true
    )"
    if [[ -n "$value" ]]; then MOUNT_BUNDLE="$value"; break; fi
  done < <(ps -eo pid=,sid=)
  [[ -n "$MOUNT_BUNDLE" ]] && break
  sleep 0.1
done
[[ -n "$MOUNT_BUNDLE" ]] || fail 'Could not discover the helper-bundle path of the normally mounted AppImage.'
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" bundle --bundle "$MOUNT_BUNDLE" >/dev/null \
  || fail 'The desktop user cannot verify the helper bundle from the normal AppImage mount.'
if sudo /usr/bin/test -r "$MOUNT_BUNDLE/bundle-manifest.json"; then
  printf 'INFO    Root can read this host AppImage FUSE mount directly; staging is still used for a portable install path.\n'
else
  printf 'INFO    Root cannot read this host AppImage FUSE mount directly, which is a normal FUSE permission model.\n'
fi
PIA_BAZZITE_STAGE8B2_MOUNT_BUNDLE="$MOUNT_BUNDLE" PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY' \
  || fail 'The verified AppImage helper bundle could not be staged into a root-readable normal-filesystem path.'
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

from pia_bazzite.helper_installation import PackagedHelperManager

bundle = Path(os.environ["PIA_BAZZITE_STAGE8B2_MOUNT_BUNDLE"])
manager = PackagedHelperManager(bundle_path=bundle)
manifest = manager._load_verified_bundle_manifest()
with manager._stage_verified_bundle(manifest) as staged:
    metadata = staged.lstat()
    if staged.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit("staging root is not a real directory")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise SystemExit("staging root is not private mode 0700")
    for relative in (
        "bundle-manifest.json",
        "tools/pia-bazzite-stage2-helper-installer.sh",
    ):
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/bin/test", "-r", str(staged / relative)],
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"root cannot read staged helper source: {relative}")
print("staged helper source is exact and root-readable")
PY
printf 'PASS    Exact AppImage helper payload can be staged privately and read by root before any helper mutation.\n'
stop_app
"$ROOT/.venv/bin/python" "$ROOT/tools/pia-bazzite-stage6c2-instance-preflight.py" >/dev/null \
  || fail 'The mount-probe AppImage instance did not stop cleanly.'

printf '\n%s\n' '--- Arm independent fail-safe before GUI install/upgrade interaction ---'
cancel_reset
RESET_COMMAND="/usr/bin/nmcli connection down id 'PIA Bazzite' >/dev/null 2>&1 || true; '$NFT_BIN' destroy table inet '$TABLE' >/dev/null 2>&1 || true"
sudo systemd-run --quiet --unit="$RESET_UNIT" --on-active="$RESET_DELAY" /bin/bash -c "$RESET_COMMAND"
if sudo systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  RESET_ARMED=1
  printf 'PASS    Independent VPN-stop/firewall-reset timer is armed for %s.\n' "$RESET_DELAY"
else
  fail 'Could not arm the Stage-8B.2 safety-reset timer.'
fi

printf '\n%s\n' '--- Missing helper: install from the real AppImage ---'
sudo bash "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" uninstall
HELPER_MUTATED=1
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" audit-installed --bundle "$BUNDLE" --expect-state missing >/dev/null
printf 'PASS    Production helper is deliberately absent before the AppImage install test.\n'

setsid env -u APPIMAGE_EXTRACT_AND_RUN "$APPIMAGE" &
APP_PID=$!
printf 'ACTION  In the %s AppImage, enable the Kill Switch if it is not already enabled.\n' "$VERSION"
printf "ACTION  Confirm 'Kill-Switch-Systemkomponente installieren?' and authorize the administrator prompt.\n"
printf 'ACTION  Do NOT connect the VPN. The test continues automatically after the exact helper is installed.\n'
for _ in $(seq 1 1800); do
  kill -0 "$APP_PID" >/dev/null 2>&1 || fail 'The AppImage exited before the missing helper was installed.'
  if PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
      "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" audit-installed --bundle "$BUNDLE" --expect-state current \
      >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" audit-installed --bundle "$BUNDLE" --expect-state current >/dev/null \
  || fail 'Timed out waiting for the AppImage to install its exact helper.'
if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -Fxq 'PIA Bazzite:wireguard'; then fail 'VPN connected during helper installation.'; fi
if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then fail 'Firewall lock appeared during helper installation.'; fi
printf 'PASS    Missing helper was installed from the real AppImage and exactly matches its embedded payload.\n'
stop_app

printf '\n%s\n' '--- Current helper: exact AppImage must not reinstall it ---'
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" snapshot-installed --bundle "$BUNDLE" --output "$SNAPSHOT_BEFORE" >/dev/null
setsid env -u APPIMAGE_EXTRACT_AND_RUN "$APPIMAGE" &
APP_PID=$!
printf 'ACTION  Authenticate the normal startup protection-status check if prompted.\n'
printf 'ACTION  There must be NO helper install/update question. Do not connect the VPN.\n'
sleep 8
kill -0 "$APP_PID" >/dev/null 2>&1 || fail 'The AppImage exited during the current-helper check.'
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" snapshot-installed --bundle "$BUNDLE" --output "$SNAPSHOT_AFTER" >/dev/null
cmp -s "$SNAPSHOT_BEFORE" "$SNAPSHOT_AFTER" || fail 'The exact current helper changed during a normal AppImage startup.'
if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then fail 'Firewall lock appeared during current-helper startup.'; fi
printf 'PASS    Exact current helper was accepted without reinstalling or changing any helper file.\n'
stop_app

printf '\n%s\n' '--- Outdated helper metadata: AppImage must require an explicit update ---'
sudo /usr/bin/rm -f -- /usr/local/libexec/pia-bazzite/kill-switch-helper-manifest.json
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" audit-installed --bundle "$BUNDLE" --expect-state outdated >/dev/null
printf 'PASS    A safe but incomplete/outdated helper installation is deliberately present.\n'
setsid env -u APPIMAGE_EXTRACT_AND_RUN "$APPIMAGE" &
APP_PID=$!
printf "ACTION  Confirm 'Kill-Switch-Systemkomponente aktualisieren?' and authorize the administrator prompt.\n"
printf 'ACTION  Do NOT connect the VPN. The test continues automatically after exact re-verification.\n'
for _ in $(seq 1 1800); do
  kill -0 "$APP_PID" >/dev/null 2>&1 || fail 'The AppImage exited before the outdated helper was updated.'
  if PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
      "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" audit-installed --bundle "$BUNDLE" --expect-state current \
      >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage8b2-appimage-inspector.py" audit-installed --bundle "$BUNDLE" --expect-state current >/dev/null \
  || fail 'Timed out waiting for the AppImage to update and reverify the helper.'
if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -Fxq 'PIA Bazzite:wireguard'; then fail 'VPN connected during helper update.'; fi
if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then fail 'Firewall lock appeared during helper update.'; fi
printf 'PASS    Outdated helper state required an AppImage update and returned to an exact root-owned match.\n'
stop_app

HELPER_MUTATED=0
restore_setting
ORIGINAL_KS=""
cancel_reset
printf 'PASS    Original Kill Switch preference restored and safety-reset timer cancelled.\n'
printf '\nALL STAGE-8B.2 REAL %s APPIMAGE HELPER HOST TESTS PASSED\n' "$VERSION"
printf 'Release candidate: %s\n' "$APPIMAGE"
printf 'Checksum: %s\n' "$CHECKSUM"
printf 'Report: %s\n' "$REPORT"
