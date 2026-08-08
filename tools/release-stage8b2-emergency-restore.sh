#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TABLE="pia_bazzite_killswitch"
RESET_UNIT="pia-bazzite-stage8b2-appimage-safety-reset"

printf 'PIA Bazzite Stage-8B.2 deliberate helper restore\n'
printf 'This restores the current source-tree production helper.\n'
printf 'It does not intentionally start a VPN or create a firewall lock.\n\n'

sudo systemctl stop "${RESET_UNIT}.timer" "${RESET_UNIT}.service" >/dev/null 2>&1 || true
sudo systemctl reset-failed "${RESET_UNIT}.service" >/dev/null 2>&1 || true

if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -Fxq 'PIA Bazzite:wireguard'; then
  printf 'ERROR: PIA Bazzite VPN is active. Use the Stage-7D Emergency Reset instead.\n' >&2
  exit 2
fi

NFT_BIN=""
if [[ -x /usr/sbin/nft ]]; then NFT_BIN=/usr/sbin/nft; elif [[ -x /usr/bin/nft ]]; then NFT_BIN=/usr/bin/nft; fi
if [[ -n "$NFT_BIN" ]] && sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
  printf 'ERROR: A production firewall lock is active. Use the Stage-7D Emergency Reset instead.\n' >&2
  exit 2
fi

sudo bash "$ROOT/tools/pia-bazzite-stage2-helper-installer.sh" install
printf '\nPASS: Current source-tree helper restored.\n'
