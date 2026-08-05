#!/usr/bin/env bash
set -uo pipefail

TABLE="pia_bazzite_killswitch_firewalld_restart_test"
RESET_UNIT="pia-bazzite-killswitch-firewalld-restart-reset"

printf 'PIA Bazzite firewalld restart test emergency reset\n'

sudo systemctl stop \
  "${RESET_UNIT}.timer" \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true
sudo systemctl reset-failed \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true

if sudo nft list table inet "$TABLE" >/dev/null 2>&1; then
  sudo nft delete table inet "$TABLE"
  printf 'Removed temporary table: inet %s\n' "$TABLE"
else
  printf 'No temporary table exists: inet %s\n' "$TABLE"
fi

if ! systemctl is-active --quiet firewalld; then
  sudo systemctl start firewalld
fi

printf 'firewalld is running and the temporary firewall lock is removed.\n'
printf 'Reconnect PIA Bazzite normally if necessary.\n'
