#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage7-crash"
REPORT="$REPORT_DIR/pia-kill-switch-crash-stage7b-host-test.txt"
RESET_UNIT="pia-bazzite-stage7b-crash-safety-reset"
RESET_DELAY="15min"
TABLE="pia_bazzite_killswitch"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-7B real GUI SIGKILL persistence test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test launches the project GUI, requires verified protected connection,\n'
printf 'kills the exact GUI process, and independently verifies that VPN, firewall,\n'
printf 'the private recovery record, and physical-path blocking survive the crash.\n\n'

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
printf 'PASS    PIA Bazzite is disconnected before the crash test.\n'

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
sudo bash "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" install
printf 'PASS    Current production helper installation completed.\n'

if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
  fail "A previous production firewall lock exists. Run the Stage-7B emergency reset first."
fi
printf 'PASS    No previous production kill-switch table is active.\n'

PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage7b-record-preflight.py"

printf '\n%s\n' '--- Arm independent fail-safe reset before launching the GUI ---'
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
  fail "The independent Stage-7B safety-reset timer is not active."
fi

printf '\n%s\n' '--- Real GUI SIGKILL persistence observation ---'
set +e
env -u PYTHONPATH "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage7b-crash-driver.py"
DRIVER_STATUS=$?
set -e

case "$DRIVER_STATUS" in
  0)
    printf '\n%s\n' '--- Deliberate post-proof cleanup ---'
    bash "$ROOT/tools/kill-switch-crash-stage7b-emergency-reset.sh"
    PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY'
import time

from pia_bazzite.pia_api import fetch_public_network_info
from pia_bazzite.logging_utils import mask_ip_address

last_error = None
for _attempt in range(10):
    try:
        info = fetch_public_network_info(timeout=8.0)
    except Exception as exc:
        last_error = exc
        time.sleep(1.0)
    else:
        print(
            "PASS    Normal public network access returned after crash-test cleanup: "
            + mask_ip_address(info.ip_address)
        )
        break
else:
    raise SystemExit(f"Normal public access did not return after cleanup: {last_error}")
PY
    cancel_reset_timer
    printf 'PASS    Safety-reset timer cancelled after verified normal connectivity returned.\n'
    printf '\nALL STAGE-7B REAL GUI CRASH HOST TESTS PASSED\n'
    printf 'Report: %s\n' "$REPORT"
    ;;
  20)
    cancel_reset_timer
    printf '\nStage 7B stopped before a production firewall lock was observed.\n'
    printf 'Report: %s\n' "$REPORT"
    exit "$DRIVER_STATUS"
    ;;
  *)
    printf '\nFAIL-CLOSED STOP\n'
    printf 'A production firewall lock was observed or could not be ruled out.\n'
    printf 'The independent reset remains armed. It stops PIA first and removes only\n'
    printf 'table %s after %s. For an immediate deliberate reset, run:\n' "$TABLE" "$RESET_DELAY"
    printf '  cd %q && bash tools/kill-switch-crash-stage7b-emergency-reset.sh\n' "$ROOT"
    printf 'Report: %s\n' "$REPORT"
    exit "$DRIVER_STATUS"
    ;;
esac
