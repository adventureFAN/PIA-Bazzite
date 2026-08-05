#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-firewalld-reload-test.txt}"

TABLE="pia_bazzite_killswitch_firewalld_test"
CHAIN="output"
RESET_UNIT="pia-bazzite-killswitch-firewalld-test-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=210

PASSED=0
WARNINGS=0
FAILURES=0
TABLE_CREATED=0
RESET_SCHEDULED=0
CLEANUP_RUNNING=0

PROFILE_UUID=""
PROFILE_NAME=""
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""
FWMARK=""
ROUTE_DEVICE=""

NFT_BIN="$(command -v nft || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-firewalld.XXXXXX.nft)"

exec > >(tee "$REPORT") 2>&1

pass() {
  printf 'PASS  %s\n' "$1"
  PASSED=$((PASSED + 1))
}

warn() {
  printf 'WARN  %s\n' "$1"
  WARNINGS=$((WARNINGS + 1))
}

fail() {
  printf 'FAIL  %s\n' "$1"
  FAILURES=$((FAILURES + 1))
}

active_profile_line() {
  nmcli -t -f UUID,NAME,TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: '$3 == "wireguard" && $4 == "piabazzite" {
        print
        exit
      }'
}

vpn_is_active() {
  [[ -n "$(active_profile_line)" ]] \
    && ip link show "$VPN_INTERFACE" >/dev/null 2>&1
}

tcp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"
  local timeout_seconds="${4:-5}"

  python3 - "$family" "$address" "$port" "$timeout_seconds" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text, timeout_text = sys.argv[1:5]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET

with socket.socket(family, socket.SOCK_STREAM) as sock:
    sock.settimeout(float(timeout_text))
    sock.connect((address, int(port_text)))
PY
}

udp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"

  python3 - "$family" "$address" "$port" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text = sys.argv[1:4]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET

with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)
    sock.connect((address, int(port_text)))
    sock.send(b"PIA-BAZZITE-FIREWALLD-RELOAD-TEST")
PY
}

expect_success() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    pass "$description"
    return 0
  fi

  fail "$description"
  return 1
}

expect_blocked() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    fail "$description (traffic unexpectedly succeeded)"
    return 1
  fi

  pass "$description"
  return 0
}

rule_packets() {
  local comment="$1"

  sudo -n nft list chain inet "$TABLE" "$CHAIN" 2>/dev/null \
    | awk -v wanted="$comment" '
        index($0, "comment \"" wanted "\"") {
          for (i = 1; i <= NF; i++) {
            if ($i == "packets" && i < NF) {
              print $(i + 1)
              exit
            }
          }
        }
      '
}

wait_for_vpn_down() {
  local attempt
  for attempt in $(seq 1 30); do
    if ! vpn_is_active; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_recent_handshake() {
  local attempt timestamp now age
  for attempt in $(seq 1 50); do
    if vpn_is_active; then
      timestamp="$(
        sudo -n wg show "$VPN_INTERFACE" latest-handshakes 2>/dev/null \
          | awk 'NF >= 2 {
              print $2
              exit
            }'
      )"

      if [[ "$timestamp" =~ ^[0-9]+$ ]] && (( timestamp > 0 )); then
        now="$(date +%s)"
        age=$((now - timestamp))
        if (( age >= 0 && age <= 30 )); then
          return 0
        fi
      fi
    fi
    sleep 1
  done
  return 1
}

cancel_reset_timer() {
  if (( RESET_SCHEDULED == 1 )); then
    sudo -n systemctl stop \
      "${RESET_UNIT}.timer" \
      "${RESET_UNIT}.service" \
      >/dev/null 2>&1 || true
    sudo -n systemctl reset-failed \
      "${RESET_UNIT}.service" \
      >/dev/null 2>&1 || true
    RESET_SCHEDULED=0
  fi
}

remove_test_table() {
  if (( TABLE_CREATED == 1 )) \
      && sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
    sudo -n nft delete table inet "$TABLE" >/dev/null 2>&1 || true
  fi
  TABLE_CREATED=0
}

reconnect_after_cleanup() {
  if [[ -z "$PROFILE_UUID" ]] || vpn_is_active; then
    return
  fi

  printf '%s\n' \
    'Cleanup: attempting to restore the original PIA Bazzite connection ...'
  timeout 65s nmcli connection up uuid "$PROFILE_UUID" >/dev/null 2>&1 \
    || warn "automatic PIA reconnection during cleanup did not succeed"
}

cleanup() {
  local exit_code=$?

  if (( CLEANUP_RUNNING == 1 )); then
    return
  fi
  CLEANUP_RUNNING=1

  set +e
  remove_test_table
  cancel_reset_timer
  reconnect_after_cleanup
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe firewalld-reload test exited early.\n'
    printf 'Its temporary nftables table and safety timer were removed.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded firewalld-reload kill-switch test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test creates a temporary kill-switch table and performs a normal' \
  'firewalld reload while PIA remains connected.' \
  '' \
  'It then briefly disconnects the VPN to verify that IPv4, IPv6, and direct' \
  'DNS traffic are still blocked after the firewalld reload.' \
  '' \
  "A root-owned automatic reset deletes the test table after ${RESET_SECONDS} seconds." \
  '' \
  'Emergency command in a second terminal:' \
  "  sudo nft delete table inet ${TABLE}" \
  '' \
  'Pause downloads, calls, games, and other network-sensitive work first.'

read -r -p 'Type RELOAD exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "RELOAD" ]]; then
  printf 'Cancelled. Nothing was changed.\n'
  exit 0
fi

printf '\n%s\n' '--- Preflight ---'

for tool in \
  nmcli wg ip nft systemctl systemd-run python3 sudo timeout firewall-cmd; do
  if command -v "$tool" >/dev/null 2>&1; then
    pass "$tool is available"
  else
    fail "$tool is missing"
  fi
done

if (( FAILURES > 0 )); then
  printf 'Required commands are missing. No firewall rule was created.\n'
  exit 1
fi

if ! sudo -v; then
  fail "sudo authorization failed"
  exit 1
fi
pass "temporary sudo authorization is available"

if ! systemctl is-active --quiet firewalld 2>/dev/null; then
  fail "firewalld is not active, so this specific test is not applicable"
  exit 1
fi
pass "firewalld is active before the test"

ACTIVE_LINE="$(active_profile_line)"
if [[ -z "$ACTIVE_LINE" ]]; then
  fail "PIA Bazzite is not connected"
  exit 1
fi

IFS=: read -r PROFILE_UUID PROFILE_NAME PROFILE_TYPE PROFILE_DEVICE \
  <<<"$ACTIVE_LINE"
pass "PIA Bazzite profile is active"
printf 'Profile: %s\n' "$PROFILE_NAME"
printf 'Interface: %s\n' "$PROFILE_DEVICE"

ENDPOINT_RAW="$(
  sudo -n wg show "$VPN_INTERFACE" endpoints 2>/dev/null \
    | awk 'NF >= 2 {
        print $2
        exit
      }'
)"

if [[ "$ENDPOINT_RAW" =~ ^\[([0-9A-Fa-f:]+)\]:([0-9]+)$ ]]; then
  ENDPOINT_IP="${BASH_REMATCH[1]}"
  ENDPOINT_PORT="${BASH_REMATCH[2]}"
  ENDPOINT_FAMILY="IPv6"
elif [[ "$ENDPOINT_RAW" =~ ^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):([0-9]+)$ ]]; then
  ENDPOINT_IP="${BASH_REMATCH[1]}"
  ENDPOINT_PORT="${BASH_REMATCH[2]}"
  ENDPOINT_FAMILY="IPv4"
else
  fail "the current numeric WireGuard endpoint could not be parsed"
  exit 1
fi
pass "the current numeric WireGuard endpoint was detected"

FWMARK="$(
  sudo -n wg show "$VPN_INTERFACE" fwmark 2>/dev/null \
    | head -n 1
)"
if [[ -z "$FWMARK" || "$FWMARK" == "off" ]]; then
  fail "the WireGuard fwmark is unavailable"
  exit 1
fi
pass "the WireGuard fwmark is available"

if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
  ROUTE_LINE="$(
    ip -4 route get "$ENDPOINT_IP" mark "$FWMARK" 2>/dev/null \
      | head -n 1
  )"
else
  ROUTE_LINE="$(
    ip -6 route get "$ENDPOINT_IP" mark "$FWMARK" 2>/dev/null \
      | head -n 1
  )"
fi

ROUTE_DEVICE="$(
  awk '{
    for (i = 1; i <= NF; i++) {
      if ($i == "dev" && i < NF) {
        print $(i + 1)
        exit
      }
    }
  }' <<<"$ROUTE_LINE"
)"

if [[ -z "$ROUTE_DEVICE" || "$ROUTE_DEVICE" == "$VPN_INTERFACE" ]]; then
  fail "the physical route to the WireGuard endpoint is unsafe or unknown"
  exit 1
fi
pass "the WireGuard endpoint uses the physical route via $ROUTE_DEVICE"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous firewalld-reload test table already exists"
  exit 1
fi
pass "no previous firewalld-reload test table exists"

printf '\n%s\n' '--- Baseline while PIA is connected ---'
expect_success \
  "public IPv4 TCP connectivity works through the VPN" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Schedule the automatic safety reset ---'
sudo -n systemctl stop \
  "${RESET_UNIT}.timer" \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true
sudo -n systemctl reset-failed \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true

if sudo -n systemd-run \
    --quiet \
    --unit="$RESET_UNIT" \
    --on-active="${RESET_SECONDS}s" \
    "$NFT_BIN" delete table inet "$TABLE"; then
  RESET_SCHEDULED=1
else
  fail "the automatic reset timer could not be created"
  exit 1
fi

if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  pass "automatic firewall reset is armed for ${RESET_SECONDS} seconds"
else
  fail "the automatic reset timer is not active"
  exit 1
fi

printf '\n%s\n' '--- Install the temporary kill-switch table atomically ---'

if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
  ENDPOINT_RULE="ip daddr $ENDPOINT_IP udp dport $ENDPOINT_PORT oifname \"$ROUTE_DEVICE\" counter accept comment \"WireGuard endpoint\""
else
  ENDPOINT_RULE="ip6 daddr $ENDPOINT_IP udp dport $ENDPOINT_PORT oifname \"$ROUTE_DEVICE\" counter accept comment \"WireGuard endpoint\""
fi

cat >"$TMP_RULESET" <<NFT
table inet $TABLE {
  chain $CHAIN {
    type filter hook output priority -100; policy accept;
    oifname "lo" counter accept comment "loopback"
    $ENDPOINT_RULE
    oifname "$VPN_INTERFACE" counter accept comment "VPN tunnel"
    counter reject with icmpx type admin-prohibited comment "block outside VPN"
  }
}
NFT

if sudo -n nft -f "$TMP_RULESET"; then
  TABLE_CREATED=1
  pass "temporary kill-switch table was installed"
else
  fail "the temporary kill-switch table could not be installed"
  exit 1
fi

expect_success \
  "IPv4 connectivity still works through piabazzite before firewalld reload" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Reload firewalld while protection is active ---'
if sudo -n firewall-cmd --reload >/dev/null 2>&1; then
  pass "firewalld completed a normal reload"
else
  fail "firewalld reload returned an error"
fi

sleep 2

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld is active after reload"
else
  fail "firewalld is not active after reload"
fi

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  pass "the PIA Bazzite test table survived the firewalld reload"
else
  fail "the PIA Bazzite test table disappeared during firewalld reload"
  exit 1
fi

expect_success \
  "IPv4 connectivity still works through piabazzite after firewalld reload" \
  tcp_probe 4 1.1.1.1 443 5

VPN_PACKETS="$(rule_packets "VPN tunnel")"
if [[ "$VPN_PACKETS" =~ ^[0-9]+$ ]] && (( VPN_PACKETS > 0 )); then
  pass "the VPN-allow rule still counts packets after firewalld reload"
else
  fail "the VPN-allow counter is missing or zero after firewalld reload"
fi

printf '\n%s\n' '--- Simulate tunnel failure after firewalld reload ---'
if timeout 35s nmcli connection down uuid "$PROFILE_UUID" >/dev/null 2>&1; then
  pass "NetworkManager accepted the external VPN disconnect"
else
  warn "nmcli returned an error while bringing the VPN down"
fi

if wait_for_vpn_down; then
  pass "piabazzite is now down"
else
  fail "piabazzite did not go down within 30 seconds"
fi

BLOCK_BEFORE="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE" =~ ^[0-9]+$ ]] || BLOCK_BEFORE=0

expect_blocked \
  "IPv4 cannot fall back after firewalld reload" \
  tcp_probe 4 1.1.1.1 443 4

expect_blocked \
  "IPv6 cannot fall back after firewalld reload" \
  tcp_probe 6 2606:4700:4700::1111 443 4

expect_blocked \
  "direct DNS-like UDP remains blocked after firewalld reload" \
  udp_probe 4 1.1.1.1 53

BLOCK_AFTER="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER" =~ ^[0-9]+$ ]] || BLOCK_AFTER=0

if (( BLOCK_AFTER > BLOCK_BEFORE )); then
  pass "the block-rule counter increased after firewalld reload (${BLOCK_BEFORE} -> ${BLOCK_AFTER})"
else
  fail "the block-rule counter did not increase after firewalld reload"
fi

printf '\n%s\n' '--- Reconnect while protection remains active ---'
if timeout 65s nmcli connection up uuid "$PROFILE_UUID" >/dev/null 2>&1; then
  pass "NetworkManager reactivated the PIA profile"
else
  fail "NetworkManager could not reactivate the PIA profile"
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake under protection"
else
  fail "no recent WireGuard handshake appeared within 50 seconds"
fi

expect_success \
  "public IPv4 connectivity works again through the VPN" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Counters before cleanup ---'
sudo -n nft list table inet "$TABLE" 2>/dev/null \
  | sed -E \
      -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/x.x.x.x/g' \
      -e 's/[0-9a-fA-F]{0,4}:[0-9a-fA-F:]+/x::x/g' \
  || true

printf '\n%s\n' '--- Deliberate cleanup ---'
remove_test_table

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "the temporary table still exists after cleanup"
else
  pass "the temporary table was removed"
fi

cancel_reset_timer
if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer" 2>/dev/null; then
  fail "the automatic reset timer is still active"
else
  pass "the automatic reset timer was cancelled"
fi

if vpn_is_active; then
  pass "PIA Bazzite is connected at the end"
else
  fail "PIA Bazzite is not connected at the end"
fi

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld is active at the end"
else
  fail "firewalld is not active at the end"
fi

printf '\n%s\n' '--- Result ---'
printf 'Passed: %d\n' "$PASSED"
printf 'Warnings: %d\n' "$WARNINGS"
printf 'Failures: %d\n' "$FAILURES"

if (( FAILURES == 0 )); then
  printf '\nALL FIREWALLD-RELOAD TESTS PASSED\n'
  printf 'The PIA Bazzite nftables table survived a normal firewalld reload,\n'
  printf 'continued blocking fallback traffic, and allowed WireGuard to reconnect.\n'
  printf 'The temporary table and safety timer were removed afterward.\n'
  exit 0
fi

printf '\nFIREWALLD-RELOAD TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'Do not use this prototype as a real kill switch yet.\n'
exit 1
