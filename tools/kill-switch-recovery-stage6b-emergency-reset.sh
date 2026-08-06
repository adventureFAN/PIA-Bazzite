#!/usr/bin/env bash
set -Eeuo pipefail

TABLE="pia_bazzite_killswitch"
RESET_UNIT="pia-bazzite-stage6b-safety-reset"

if [[ -x /usr/sbin/nft ]]; then
  NFT_BIN=/usr/sbin/nft
elif [[ -x /usr/bin/nft ]]; then
  NFT_BIN=/usr/bin/nft
else
  printf 'ERROR: nft is missing from the approved system paths.\n' >&2
  exit 1
fi

printf 'PIA Bazzite Stage-6B deliberate emergency reset\n'
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
printf 'PASS: PIA VPN stopped and production kill-switch table is absent.\n'
