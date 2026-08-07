#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TABLE="pia_bazzite_killswitch"
RESET_UNIT="pia-bazzite-stage7b-crash-safety-reset"

if [[ -x /usr/sbin/nft ]]; then
  NFT_BIN=/usr/sbin/nft
elif [[ -x /usr/bin/nft ]]; then
  NFT_BIN=/usr/bin/nft
else
  printf 'ERROR: nft is missing from the approved system paths.\n' >&2
  exit 1
fi

[[ -x "$ROOT/.venv/bin/python" ]] \
  || { printf 'ERROR: .venv/bin/python is missing.\n' >&2; exit 1; }

printf 'PIA Bazzite Stage-7B deliberate crash-test reset\n'
printf 'The PIA WireGuard profile is stopped first; only then is the fixed production table removed.\n\n'

sudo -v
nmcli connection down id 'PIA Bazzite' >/dev/null 2>&1 || true
sudo "$NFT_BIN" destroy table inet "$TABLE" >/dev/null 2>&1 || true
sudo systemctl stop \
  "${RESET_UNIT}.timer" \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true
sudo systemctl reset-failed "${RESET_UNIT}.service" >/dev/null 2>&1 || true

if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
  printf 'ERROR: The production kill-switch table is still present.\n' >&2
  exit 1
fi
if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
    | grep -Fxq 'PIA Bazzite:wireguard'; then
  printf 'ERROR: The PIA WireGuard profile is still active.\n' >&2
  exit 1
fi

PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" - <<'PY'
from pia_bazzite.kill_switch_crash_state import CrashRecoveryStore
from pia_bazzite.settings import crash_recovery_path

store = CrashRecoveryStore(crash_recovery_path())
store.clear()
if store.load() is not None:
    raise SystemExit("Crash-recovery record is still present.")
print("PASS: Crash-recovery record is absent.")
PY

printf 'PASS: PIA VPN stopped and production kill-switch table is absent.\n'
