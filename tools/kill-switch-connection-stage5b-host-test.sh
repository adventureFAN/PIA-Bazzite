#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage5-connection"
REPORT="$REPORT_DIR/pia-kill-switch-connection-stage5b-host-test.txt"
RESET_UNIT="pia-bazzite-stage5b-safety-reset"
RESET_DELAY="10min"
TABLE="pia_bazzite_killswitch"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-5B real host connection test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test installs the verified production helper, creates a temporary\n'
printf 'root-owned safety-reset timer, connects real PIA, and deliberately disconnects it.\n\n'

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
command -v nmcli >/dev/null 2>&1 || fail "nmcli is missing."
command -v systemd-run >/dev/null 2>&1 || fail "systemd-run is missing."

if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
    | grep -Fxq 'PIA Bazzite:wireguard'; then
  fail "PIA Bazzite is already connected. Disconnect it and close the normal app first."
fi
printf 'PASS    PIA Bazzite is disconnected before the host test.\n'

if [[ -x /usr/sbin/nft ]]; then
  NFT_BIN=/usr/sbin/nft
elif [[ -x /usr/bin/nft ]]; then
  NFT_BIN=/usr/bin/nft
else
  fail "nft is missing from the approved system paths."
fi
printf 'PASS    nftables executable: %s\n' "$NFT_BIN"

printf '\n%s\n' '--- Root authorization and production helper installation ---'
sudo -v || fail "sudo authorization failed."
sudo bash "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" install
printf 'PASS    Stage-5 production helper installation completed.\n'

printf '\n%s\n' '--- Arm independent safety reset ---'
cancel_reset_timer
sudo systemd-run \
  --quiet \
  --unit="$RESET_UNIT" \
  --on-active="$RESET_DELAY" \
  "$NFT_BIN" destroy table inet "$TABLE"
if sudo systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  printf 'PASS    Independent safety reset is armed for %s.\n' "$RESET_DELAY"
else
  fail "The independent safety-reset timer is not active."
fi

printf '\n%s\n' '--- Real fail-closed connect and intentional disconnect ---'
set +e
env -u PYTHONPATH "$ROOT/.venv/bin/python" \
  "$ROOT/tools/pia-bazzite-stage5b-host-driver.py" "$@"
DRIVER_STATUS=$?
set -e

case "$DRIVER_STATUS" in
  0)
    cancel_reset_timer
    printf 'PASS    Safety-reset timer cancelled after verified normal connectivity returned.\n'
    printf '\nALL STAGE-5B REAL HOST TESTS PASSED\n'
    printf 'Report: %s\n' "$REPORT"
    ;;
  20)
    cancel_reset_timer
    printf '\nStage 5B stopped before a firewall lock was expected to remain active.\n'
    printf 'Report: %s\n' "$REPORT"
    exit "$DRIVER_STATUS"
    ;;
  *)
    printf '\nFAIL-CLOSED STOP\n'
    printf 'The production firewall may still be active. The independent reset timer\n'
    printf 'has deliberately been left armed and will remove only table %s after %s.\n' \
      "$TABLE" "$RESET_DELAY"
    printf 'For an immediate deliberate reset, run:\n'
    printf '  cd %q && bash tools/kill-switch-connection-stage5b-emergency-reset.sh\n' "$ROOT"
    printf 'Report: %s\n' "$REPORT"
    exit "$DRIVER_STATUS"
    ;;
esac
