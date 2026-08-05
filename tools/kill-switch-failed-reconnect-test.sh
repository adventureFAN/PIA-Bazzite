#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-failed-reconnect-test.txt}"

TABLE="pia_bazzite_killswitch_failed_reconnect_test"
CHAIN="output"
SET4="allowed_endpoints_v4"
SET6="allowed_endpoints_v6"
RESET_UNIT="pia-bazzite-killswitch-failed-reconnect-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=300
BLOCKED_ATTEMPT_SECONDS=18

PASSED=0
WARNINGS=0
FAILURES=0
TABLE_CREATED=0
RESET_SCHEDULED=0
CLEANUP_RUNNING=0

VPN_UUID=""
VPN_NAME=""
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""
FWMARK=""
ROUTE_DEVICE=""
OLD_HANDSHAKE=""

NFT_BIN="$(command -v nft || true)"
NMCLI_BIN="$(command -v nmcli || true)"
BASH_BIN="$(command -v bash || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-failed-reconnect.XXXXXX.nft)"

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

active_vpn_line() {
  nmcli -t -f UUID,NAME,TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: '$3 == "wireguard" && $4 == "piabazzite" {
        print
        exit
      }'
}

vpn_is_active() {
  [[ -n "$(active_vpn_line)" ]] \
    && ip link show "$VPN_INTERFACE" >/dev/null 2>&1
}

current_handshake() {
  sudo -n wg show "$VPN_INTERFACE" latest-handshakes 2>/dev/null \
    | awk 'NF >= 2 {
        print $2
        exit
      }'
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
    sock.send(b"PIA-BAZZITE-FAILED-RECONNECT-TEST")
PY
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

add_endpoint() {
  if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
    sudo -n nft add element inet "$TABLE" "$SET4" \
      "{ $ENDPOINT_IP . $ENDPOINT_PORT }" >/dev/null 2>&1
  else
    sudo -n nft add element inet "$TABLE" "$SET6" \
      "{ $ENDPOINT_IP . $ENDPOINT_PORT }" >/dev/null 2>&1
  fi
}

delete_endpoint() {
  if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
    sudo -n nft delete element inet "$TABLE" "$SET4" \
      "{ $ENDPOINT_IP . $ENDPOINT_PORT }" >/dev/null 2>&1
  else
    sudo -n nft delete element inet "$TABLE" "$SET6" \
      "{ $ENDPOINT_IP . $ENDPOINT_PORT }" >/dev/null 2>&1
  fi
}

endpoint_is_present() {
  local set_name

  if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
    set_name="$SET4"
  else
    set_name="$SET6"
  fi

  sudo -n nft list set inet "$TABLE" "$set_name" 2>/dev/null \
    | grep -Fq "$ENDPOINT_IP . $ENDPOINT_PORT"
}

wait_for_vpn_down() {
  local attempt
  for attempt in $(seq 1 35); do
    if ! vpn_is_active; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_recent_handshake() {
  local attempt timestamp now age
  for attempt in $(seq 1 70); do
    if vpn_is_active; then
      timestamp="$(current_handshake)"
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

restore_vpn() {
  if [[ -z "$VPN_UUID" ]] || vpn_is_active; then
    return
  fi

  printf '%s\n' \
    'Cleanup: attempting to restore the PIA WireGuard profile ...'
  timeout 85s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1 \
    || warn "automatic PIA restoration during cleanup did not succeed"
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
  restore_vpn
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe failed-reconnect test exited early.\n'
    printf 'Its temporary firewall table and safety timer were removed.\n'
    printf 'PIA was restored where possible.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded failed-reconnect kill-switch test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test deliberately makes the current WireGuard endpoint unreachable.' \
  '' \
  'The VPN profile is brought down and activated again while its endpoint is' \
  'withheld from the kill-switch allow set. NetworkManager may report the' \
  'profile as active, but WireGuard must not complete a fresh handshake.' \
  '' \
  'Ordinary IPv4, IPv6, and direct DNS traffic must remain blocked.' \
  'The endpoint is then restored and WireGuard must recover under protection.' \
  '' \
  "A root-owned safety unit removes the table and reconnects PIA after" \
  "${RESET_SECONDS} seconds." \
  '' \
  'Emergency command:' \
  "  sudo nft delete table inet ${TABLE}"

read -r -p 'Type FAILSAFE exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "FAILSAFE" ]]; then
  printf 'Cancelled. Nothing was changed.\n'
  exit 0
fi

printf '\n%s\n' '--- Preflight ---'

for tool in \
  nmcli wg ip nft systemctl systemd-run python3 sudo timeout bash; do
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

VPN_LINE="$(active_vpn_line)"
if [[ -z "$VPN_LINE" ]]; then
  fail "PIA Bazzite is not connected"
  exit 1
fi

IFS=: read -r VPN_UUID VPN_NAME VPN_TYPE VPN_DEVICE <<<"$VPN_LINE"
pass "PIA Bazzite WireGuard profile is active"
printf 'VPN profile: %s\n' "$VPN_NAME"

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
  fail "the physical route to the endpoint is unsafe or unknown"
  exit 1
fi
pass "the endpoint has a physical route via $ROUTE_DEVICE"

OLD_HANDSHAKE="$(current_handshake)"
if [[ ! "$OLD_HANDSHAKE" =~ ^[0-9]+$ ]] || (( OLD_HANDSHAKE <= 0 )); then
  fail "the current handshake timestamp is unavailable"
  exit 1
fi
pass "the current WireGuard handshake timestamp is available"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous failed-reconnect test table already exists"
  exit 1
fi
pass "no previous failed-reconnect test table exists"

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works through the VPN before the test"
else
  fail "public IPv4 connectivity does not work before the test"
  exit 1
fi

printf '\n%s\n' '--- Schedule automatic safety recovery ---'

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
    "$BASH_BIN" -c '
      "$1" delete table inet pia_bazzite_killswitch_failed_reconnect_test \
        >/dev/null 2>&1 || true
      "$2" connection up uuid "$3" >/dev/null 2>&1 || true
    ' bash "$NFT_BIN" "$NMCLI_BIN" "$VPN_UUID"; then
  RESET_SCHEDULED=1
else
  fail "the automatic safety recovery unit could not be created"
  exit 1
fi

if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  pass "automatic safety recovery is armed for ${RESET_SECONDS} seconds"
else
  fail "the automatic safety recovery timer is not active"
  exit 1
fi

printf '\n%s\n' '--- Install the temporary kill-switch table ---'

cat >"$TMP_RULESET" <<NFT
table inet $TABLE {
  set $SET4 {
    type ipv4_addr . inet_service
  }

  set $SET6 {
    type ipv6_addr . inet_service
  }

  chain $CHAIN {
    type filter hook output priority -100; policy accept;

    oifname "lo" counter accept comment "loopback"

    ip daddr . udp dport @$SET4 \
      oifname "$ROUTE_DEVICE" counter accept comment "allowed endpoint IPv4"

    ip6 daddr . udp dport @$SET6 \
      oifname "$ROUTE_DEVICE" counter accept comment "allowed endpoint IPv6"

    oifname "$VPN_INTERFACE" counter accept comment "VPN tunnel"

    counter reject with icmpx type admin-prohibited \
      comment "block outside VPN"
  }
}
NFT

if sudo -n nft -f "$TMP_RULESET"; then
  TABLE_CREATED=1
  pass "temporary failed-reconnect kill-switch table was installed"
else
  fail "the temporary nftables table could not be installed"
  exit 1
fi

if add_endpoint; then
  pass "the current PIA endpoint was added to the allow set"
else
  fail "the current PIA endpoint could not be added"
  exit 1
fi

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "VPN connectivity still works under protection"
else
  fail "VPN connectivity failed after installing the table"
  exit 1
fi

printf '\n%s\n' '--- Make the endpoint unreachable ---'

if delete_endpoint; then
  pass "the PIA endpoint was removed from the allow set"
else
  fail "the PIA endpoint could not be removed"
fi

if endpoint_is_present; then
  fail "the endpoint is still present in the allow set"
else
  pass "the endpoint allow set is empty"
fi

if timeout 40s nmcli connection down uuid "$VPN_UUID" >/dev/null 2>&1; then
  pass "NetworkManager deactivated the existing PIA profile"
else
  warn "nmcli returned an error while deactivating the PIA profile"
fi

if wait_for_vpn_down; then
  pass "piabazzite is down before the failed reconnect attempt"
else
  fail "piabazzite did not go down before the failed reconnect attempt"
fi

BLOCK_BEFORE="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE" =~ ^[0-9]+$ ]] || BLOCK_BEFORE=0

ATTEMPT_START="$(date +%s)"

if timeout 25s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1; then
  pass "NetworkManager accepted the reconnect activation request"
else
  warn "NetworkManager returned an error for the blocked reconnect request"
fi

printf 'Holding the endpoint blocked for %ss ...\n' "$BLOCKED_ATTEMPT_SECONDS"
sleep "$BLOCKED_ATTEMPT_SECONDS"

NEW_HANDSHAKE="$(current_handshake)"
if [[ "$NEW_HANDSHAKE" =~ ^[0-9]+$ ]] \
    && (( NEW_HANDSHAKE >= ATTEMPT_START )); then
  fail "WireGuard unexpectedly completed a fresh handshake while the endpoint was blocked"
else
  pass "WireGuard did not complete a fresh handshake while the endpoint was blocked"
fi

expect_blocked \
  "IPv4 cannot fall back during the failed reconnect" \
  tcp_probe 4 1.1.1.1 443 4

expect_blocked \
  "IPv6 cannot fall back during the failed reconnect" \
  tcp_probe 6 2606:4700:4700::1111 443 4

expect_blocked \
  "direct DNS-like UDP remains blocked during the failed reconnect" \
  udp_probe 4 1.1.1.1 53

BLOCK_AFTER="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER" =~ ^[0-9]+$ ]] || BLOCK_AFTER=0

if (( BLOCK_AFTER > BLOCK_BEFORE )); then
  pass "the block counter increased during the failed reconnect (${BLOCK_BEFORE} -> ${BLOCK_AFTER})"
else
  fail "the block counter did not increase during the failed reconnect"
fi

printf '\n%s\n' '--- Restore the endpoint and recover WireGuard ---'

if add_endpoint; then
  pass "the PIA endpoint was restored to the allow set"
else
  fail "the PIA endpoint could not be restored"
fi

if endpoint_is_present; then
  pass "the PIA endpoint is present in the allow set again"
else
  fail "the PIA endpoint is missing from the allow set"
fi

if vpn_is_active; then
  pass "the WireGuard profile remained logically active for automatic recovery"
else
  if timeout 85s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1; then
    pass "NetworkManager reactivated the PIA profile after endpoint restoration"
  else
    fail "NetworkManager could not reactivate the PIA profile"
  fi
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake after endpoint restoration"
else
  fail "WireGuard did not complete a fresh handshake after endpoint restoration"
fi

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works again through the restored VPN"
else
  fail "public IPv4 connectivity did not return through the VPN"
fi

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld remained active throughout the test"
else
  warn "firewalld is not active at the end"
fi

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
  fail "the automatic safety timer is still active"
else
  pass "the automatic safety timer was cancelled"
fi

if vpn_is_active; then
  pass "PIA Bazzite WireGuard is connected at the end"
else
  fail "PIA Bazzite WireGuard is not connected at the end"
fi

printf '\n%s\n' '--- Result ---'
printf 'Passed: %d\n' "$PASSED"
printf 'Warnings: %d\n' "$WARNINGS"
printf 'Failures: %d\n' "$FAILURES"

if (( FAILURES == 0 )); then
  printf '\nALL FAILED-RECONNECT TESTS PASSED\n'
  printf 'WireGuard could not handshake while its endpoint was withheld, fallback\n'
  printf 'traffic remained blocked, and the tunnel recovered after the endpoint was\n'
  printf 'restored without disabling the kill switch.\n'
  printf 'The temporary table and safety timer were removed.\n'
  exit 0
fi

printf '\nFAILED-RECONNECT TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'PIA was restored where possible.\n'
exit 1
