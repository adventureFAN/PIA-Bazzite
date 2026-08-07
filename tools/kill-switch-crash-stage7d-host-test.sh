#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage7-crash"
REPORT="$REPORT_DIR/pia-kill-switch-crash-stage7d-host-test.txt"
RESET_UNIT="pia-bazzite-stage7d-adversarial-safety-reset"
RESET_DELAY="15min"
TABLE="pia_bazzite_killswitch"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-7D adversarial recovery and Emergency Reset host test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This final Stage-7 host test refuses a corrupted recovery record on a clean host,\n'
printf 'creates a deliberate verified firewall lock without a recovery record, requires the\n'
printf 'real GUI to refuse takeover while the independent sentinel stays clean, then proves\n'
printf 'the documented VPN-first Emergency Reset and a clean automatic GUI restart.\n\n'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

cancel_reset_timer() {
  sudo systemctl stop \
    "${RESET_UNIT}.timer" \
    "${RESET_UNIT}.service" \
    >/dev/null 2>&1 || true
  sudo systemctl reset-failed "${RESET_UNIT}.service" >/dev/null 2>&1 || true
}

SUDO_KEEPALIVE_PID=""
stop_sudo_keepalive() {
  if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
    kill "$SUDO_KEEPALIVE_PID" >/dev/null 2>&1 || true
    wait "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
  fi
}
trap stop_sudo_keepalive EXIT

[[ -x "$ROOT/.venv/bin/python" ]] \
  || fail ".venv/bin/python is missing. Run the normal project setup first."
[[ -x /usr/bin/python3 ]] || fail "/usr/bin/python3 is missing."
[[ -x /usr/bin/sudo ]] || fail "/usr/bin/sudo is missing."
command -v nmcli >/dev/null 2>&1 || fail "nmcli is missing."
command -v systemd-run >/dev/null 2>&1 || fail "systemd-run is missing."

"$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage6c2-instance-preflight.py" \
  || fail "Close every existing PIA Bazzite window and tray instance before this test."
printf 'PASS    No running PIA Bazzite instance was detected.\n'

if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
    | grep -Fxq 'PIA Bazzite:wireguard'; then
  fail "PIA Bazzite is already connected. Disconnect it and close the app first."
fi
printf 'PASS    PIA Bazzite is disconnected before the Stage-7D host test.\n'

if [[ -x /usr/sbin/nft ]]; then
  NFT_BIN=/usr/sbin/nft
elif [[ -x /usr/bin/nft ]]; then
  NFT_BIN=/usr/bin/nft
else
  fail "nft is missing from the approved system paths."
fi
printf 'PASS    nftables executable: %s\n' "$NFT_BIN"

printf '\n%s\n' '--- Root authorization and verified helper installation ---'
sudo -v || fail "sudo authorization failed."
(
  while sleep 30; do
    sudo -n -v >/dev/null 2>&1 || exit 0
  done
) &
SUDO_KEEPALIVE_PID=$!
sudo bash "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" install
printf 'PASS    Current production helper installation completed.\n'

if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
  fail "A previous production firewall lock exists. Run the Stage-7D emergency reset first."
fi
printf 'PASS    No previous production kill-switch table is active.\n'

PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage7b-record-preflight.py" \
  || fail "A previous unsafe recovery path exists. Run the Stage-7D emergency reset first."

printf '\n%s\n' '--- Arm independent fail-safe reset before adversarial host actions ---'
cancel_reset_timer
RESET_COMMAND="/usr/bin/nmcli connection down id 'PIA Bazzite' >/dev/null 2>&1 || true; '$NFT_BIN' destroy table inet '$TABLE' >/dev/null 2>&1 || true"
sudo systemd-run \
  --quiet \
  --unit="$RESET_UNIT" \
  --on-active="$RESET_DELAY" \
  /bin/bash -c "$RESET_COMMAND"
if sudo systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  printf 'PASS    Independent VPN-stop and firewall-reset timer is armed for %s.\n' "$RESET_DELAY"
else
  fail "The independent Stage-7D safety-reset timer is not active."
fi

printf '\n%s\n' '--- Real Stage-7D adversarial recovery observation ---'
set +e
env -u PYTHONPATH "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage7d-adversarial-driver.py"
DRIVER_STATUS=$?
set -e

case "$DRIVER_STATUS" in
  0)
    cancel_reset_timer
    printf 'PASS    Safety-reset timer is inactive after the verified Stage-7D cleanup.\n'
    printf '\nALL STAGE-7D REAL GUI ADVERSARIAL RECOVERY HOST TESTS PASSED\n'
    printf 'Report: %s\n' "$REPORT"
    ;;
  20)
    cancel_reset_timer
    printf '\nStage 7D stopped before a production firewall lock was observed.\n'
    printf 'If an intentionally corrupted recovery path remains, run:\n'
    printf '  cd %q && bash tools/kill-switch-crash-stage7d-emergency-reset.sh\n' "$ROOT"
    printf 'Report: %s\n' "$REPORT"
    exit "$DRIVER_STATUS"
    ;;
  *)
    printf '\nFAIL-CLOSED STOP\n'
    printf 'A production firewall lock was observed or could not be ruled out.\n'
    printf 'The independent reset remains armed. It stops PIA first and removes only\n'
    printf 'table %s after %s. For an immediate deliberate reset, run:\n' "$TABLE" "$RESET_DELAY"
    printf '  cd %q && bash tools/kill-switch-crash-stage7d-emergency-reset.sh\n' "$ROOT"
    printf 'Report: %s\n' "$REPORT"
    exit "$DRIVER_STATUS"
    ;;
esac
