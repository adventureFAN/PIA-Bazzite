#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-server-switch-test.txt}"

TABLE="pia_bazzite_killswitch_switch_test"
CHAIN="output"
SET4="allowed_endpoints_v4"
SET6="allowed_endpoints_v6"
RESET_UNIT="pia-bazzite-killswitch-switch-test-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=240
SWITCH_WAIT_SECONDS=150

PASSED=0
WARNINGS=0
FAILURES=0
RESET_SCHEDULED=0
TABLE_CREATED=0
CLEANUP_RUNNING=0
NFT_BIN="$(command -v nft || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-switch.XXXXXX.nft)"

OLD_ENDPOINT_IP=""
OLD_ENDPOINT_PORT=""
OLD_ENDPOINT_FAMILY=""
OLD_ENDPOINT_RAW=""
OLD_PROFILE_UUID=""
OLD_FWMARK=""
OLD_HANDSHAKE=""

NEW_ENDPOINT_IP=""
NEW_ENDPOINT_PORT=""
NEW_ENDPOINT_FAMILY=""
NEW_ENDPOINT_RAW=""
NEW_PROFILE_UUID=""
NEW_FWMARK=""
NEW_HANDSHAKE=""

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

mask_ipv4() {
  local value="$1"
  awk -F. 'NF == 4 { printf "%s.%s.x.x", $1, $2; exit }' <<<"$value"
}

mask_ipv6() {
  local value="$1"
  printf '%s::…' "${value%%:*}"
}

display_endpoint() {
  local family="$1"
  local ip="$2"
  local port="$3"

  if [[ "$family" == "IPv4" ]]; then
    printf '%s:%s' "$(mask_ipv4 "$ip")" "$port"
  else
    printf '[%s]:%s' "$(mask_ipv6 "$ip")" "$port"
  fi
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

parse_endpoint() {
  local raw="$1"

  PARSED_IP=""
  PARSED_PORT=""
  PARSED_FAMILY=""

  if [[ "$raw" =~ ^\[([0-9A-Fa-f:]+)\]:([0-9]+)$ ]]; then
    PARSED_IP="${BASH_REMATCH[1]}"
    PARSED_PORT="${BASH_REMATCH[2]}"
    PARSED_FAMILY="IPv6"
    return 0
  fi

  if [[ "$raw" =~ ^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):([0-9]+)$ ]]; then
    PARSED_IP="${BASH_REMATCH[1]}"
    PARSED_PORT="${BASH_REMATCH[2]}"
    PARSED_FAMILY="IPv4"
    return 0
  fi

  return 1
}

current_endpoint_raw() {
  sudo -n wg show "$VPN_INTERFACE" endpoints 2>/dev/null \
    | awk 'NF >= 2 {
        print $2
        exit
      }'
}

current_fwmark() {
  sudo -n wg show "$VPN_INTERFACE" fwmark 2>/dev/null \
    | head -n 1
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

marked_physical_udp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"
  local device="$4"
  local fwmark="$5"

  # SO_MARK selects NetworkManager's physical endpoint route. Binding the
  # socket to the physical device prevents the active VPN default route from
  # turning this into ordinary, permitted tunnel traffic.
  sudo -n python3 - \
    "$family" "$address" "$port" "$device" "$fwmark" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text, device, fwmark_text = sys.argv[1:6]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET
so_mark = getattr(socket, "SO_MARK", 36)
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.settimeout(1.0)
    sock.setsockopt(socket.SOL_SOCKET, so_mark, int(fwmark_text, 0))
    sock.setsockopt(
        socket.SOL_SOCKET,
        so_bindtodevice,
        device.encode("utf-8") + b"\0",
    )

    try:
        sock.connect((address, int(port_text)))
        sock.send(b"PIA-BAZZITE-PHYSICAL-ENDPOINT-PROBE")
    except OSError:
        # A local nftables REJECT can make send/connect fail synchronously.
        # The authoritative result is the nftables counter checked afterward.
        pass
PY
}

set_contains_endpoint() {
  local family="$1"
  local address="$2"
  local port="$3"
  local set_name

  if [[ "$family" == "IPv4" ]]; then
    set_name="$SET4"
  else
    set_name="$SET6"
  fi

  sudo -n nft list set inet "$TABLE" "$set_name" 2>/dev/null \
    | grep -Fq "$address . $port"
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

add_endpoint() {
  local family="$1"
  local ip="$2"
  local port="$3"

  if [[ "$family" == "IPv4" ]]; then
    sudo -n nft add element inet "$TABLE" "$SET4" \
      "{ $ip . $port }" >/dev/null 2>&1
  else
    sudo -n nft add element inet "$TABLE" "$SET6" \
      "{ $ip . $port }" >/dev/null 2>&1
  fi
}

delete_endpoint() {
  local family="$1"
  local ip="$2"
  local port="$3"

  if [[ "$family" == "IPv4" ]]; then
    sudo -n nft delete element inet "$TABLE" "$SET4" \
      "{ $ip . $port }" >/dev/null 2>&1
  else
    sudo -n nft delete element inet "$TABLE" "$SET6" \
      "{ $ip . $port }" >/dev/null 2>&1
  fi
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

cleanup() {
  local exit_code=$?

  if (( CLEANUP_RUNNING == 1 )); then
    return
  fi
  CLEANUP_RUNNING=1

  set +e
  remove_test_table
  cancel_reset_timer
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe server-switch test exited early.\n'
    printf 'Its temporary nftables table and safety timer were removed.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded server-switch kill-switch test v2\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test keeps a temporary kill switch active while PIA Bazzite changes' \
  'from the current PIA server to a different server.' \
  '' \
  'You will manually choose another country from the PIA Bazzite tray menu.' \
  'Choose a clearly different country so the WireGuard endpoint changes.' \
  '' \
  "A root-owned automatic reset will delete the test table after ${RESET_SECONDS} seconds." \
  '' \
  'Emergency command in a second terminal:' \
  "  sudo nft delete table inet ${TABLE}" \
  '' \
  'Pause downloads, calls, games, and other network-sensitive work first.'

read -r -p 'Type SWITCH exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "SWITCH" ]]; then
  printf 'Cancelled. Nothing was changed.\n'
  exit 0
fi

printf '\n%s\n' '--- Preflight immediately before the switch test ---'

for tool in nmcli wg ip nft systemctl systemd-run python3 sudo timeout; do
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

ACTIVE_LINE="$(active_profile_line)"
if [[ -z "$ACTIVE_LINE" ]]; then
  fail "PIA Bazzite is not connected"
  exit 1
fi

IFS=: read -r OLD_PROFILE_UUID PROFILE_NAME PROFILE_TYPE PROFILE_DEVICE \
  <<<"$ACTIVE_LINE"
pass "PIA Bazzite profile is active"
printf 'Interface: %s\n' "$PROFILE_DEVICE"

OLD_ENDPOINT_RAW="$(current_endpoint_raw)"
if ! parse_endpoint "$OLD_ENDPOINT_RAW"; then
  fail "the current WireGuard endpoint could not be parsed"
  exit 1
fi
OLD_ENDPOINT_IP="$PARSED_IP"
OLD_ENDPOINT_PORT="$PARSED_PORT"
OLD_ENDPOINT_FAMILY="$PARSED_FAMILY"
pass "the current numeric WireGuard endpoint was detected"
printf 'Current endpoint: %s (%s, masked)\n' \
  "$(display_endpoint "$OLD_ENDPOINT_FAMILY" "$OLD_ENDPOINT_IP" "$OLD_ENDPOINT_PORT")" \
  "$OLD_ENDPOINT_FAMILY"

OLD_FWMARK="$(current_fwmark)"
if [[ -z "$OLD_FWMARK" || "$OLD_FWMARK" == "off" ]]; then
  fail "the current WireGuard fwmark is unavailable"
  exit 1
fi
pass "the current WireGuard fwmark is available"
printf 'Current fwmark: %s\n' "$OLD_FWMARK"

OLD_HANDSHAKE="$(current_handshake)"
if [[ ! "$OLD_HANDSHAKE" =~ ^[0-9]+$ ]] || (( OLD_HANDSHAKE <= 0 )); then
  fail "the current WireGuard handshake timestamp is unavailable"
  exit 1
fi
pass "the current WireGuard handshake timestamp is available"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous server-switch test table already exists"
  printf 'Emergency cleanup command:\n'
  printf '  sudo nft delete table inet %s\n' "$TABLE"
  exit 1
fi
pass "no previous server-switch test table exists"

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld is active before the test"
  FIREWALLD_WAS_ACTIVE=1
else
  warn "firewalld is not active before the test"
  FIREWALLD_WAS_ACTIVE=0
fi

printf '\n%s\n' '--- Baseline on the current PIA server ---'
expect_success \
  "public IPv4 TCP connectivity works through the current VPN" \
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

printf '\n%s\n' '--- Install the temporary nftables table atomically ---'
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
    oifname "$VPN_INTERFACE" counter accept comment "VPN tunnel"
    ip daddr . udp dport @$SET4 counter accept comment "allowed endpoint IPv4"
    ip6 daddr . udp dport @$SET6 counter accept comment "allowed endpoint IPv6"
    counter reject with icmpx type admin-prohibited comment "block outside VPN"
  }
}
NFT

if sudo -n nft -f "$TMP_RULESET"; then
  TABLE_CREATED=1
  pass "temporary server-switch kill-switch table was installed"
else
  fail "the temporary nftables table could not be installed"
  exit 1
fi

if add_endpoint \
    "$OLD_ENDPOINT_FAMILY" \
    "$OLD_ENDPOINT_IP" \
    "$OLD_ENDPOINT_PORT"; then
  pass "the current PIA endpoint was added to the allow set"
else
  fail "the current PIA endpoint could not be added"
  exit 1
fi

if (( FIREWALLD_WAS_ACTIVE == 1 )) \
    && systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld remained active beside the test table"
else
  warn "firewalld state changed during table installation"
fi

expect_success \
  "IPv4 connectivity still works through the current VPN under protection" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Manual PIA Bazzite server switch ---'
printf '%s\n' \
  'NOW use the PIA Bazzite SYSTEM-TRAY MENU to choose a DIFFERENT COUNTRY.' \
  'Do not press Disconnect. Choose one of the server entries in the tray menu.' \
  '' \
  "The test will watch for a new endpoint for up to ${SWITCH_WAIT_SECONDS} seconds."

SWITCH_STARTED="$(date +%s)"
DEADLINE=$((SWITCH_STARTED + SWITCH_WAIT_SECONDS))
SAW_INTERFACE_DOWN=0
NEW_ENDPOINT_ADDED=0
SWITCH_SUCCESS=0
LAST_STATUS_SECOND=-1

while (( $(date +%s) <= DEADLINE )); do
  NOW="$(date +%s)"
  ELAPSED=$((NOW - SWITCH_STARTED))

  if (( ELAPSED != LAST_STATUS_SECOND && ELAPSED % 10 == 0 )); then
    printf 'Waiting for changed endpoint ... %ss/%ss\n' \
      "$ELAPSED" "$SWITCH_WAIT_SECONDS"
    LAST_STATUS_SECOND="$ELAPSED"
  fi

  if ! ip link show "$VPN_INTERFACE" >/dev/null 2>&1; then
    SAW_INTERFACE_DOWN=1
    sleep 0.20
    continue
  fi

  CANDIDATE_RAW="$(current_endpoint_raw)"
  if [[ -z "$CANDIDATE_RAW" || "$CANDIDATE_RAW" == "$OLD_ENDPOINT_RAW" ]]; then
    sleep 0.20
    continue
  fi

  if ! parse_endpoint "$CANDIDATE_RAW"; then
    sleep 0.20
    continue
  fi

  if (( NEW_ENDPOINT_ADDED == 0 )); then
    NEW_ENDPOINT_RAW="$CANDIDATE_RAW"
    NEW_ENDPOINT_IP="$PARSED_IP"
    NEW_ENDPOINT_PORT="$PARSED_PORT"
    NEW_ENDPOINT_FAMILY="$PARSED_FAMILY"

    printf 'Detected new endpoint: %s (%s, masked)\n' \
      "$(display_endpoint "$NEW_ENDPOINT_FAMILY" "$NEW_ENDPOINT_IP" "$NEW_ENDPOINT_PORT")" \
      "$NEW_ENDPOINT_FAMILY"

    if add_endpoint \
        "$NEW_ENDPOINT_FAMILY" \
        "$NEW_ENDPOINT_IP" \
        "$NEW_ENDPOINT_PORT"; then
      NEW_ENDPOINT_ADDED=1
      pass "the new PIA endpoint was added while the kill switch remained active"
    else
      fail "the new PIA endpoint could not be added to the allow set"
      break
    fi
  fi

  NEW_FWMARK="$(current_fwmark)"
  NEW_HANDSHAKE="$(current_handshake)"
  NEW_ACTIVE_LINE="$(active_profile_line)"

  if [[ -n "$NEW_ACTIVE_LINE" ]]; then
    IFS=: read -r NEW_PROFILE_UUID NEW_PROFILE_NAME NEW_PROFILE_TYPE \
      NEW_PROFILE_DEVICE <<<"$NEW_ACTIVE_LINE"
  fi

  if [[ "$NEW_HANDSHAKE" =~ ^[0-9]+$ ]] \
      && (( NEW_HANDSHAKE >= SWITCH_STARTED )); then
    SWITCH_SUCCESS=1
    break
  fi

  sleep 0.25
done

if (( SAW_INTERFACE_DOWN == 1 )); then
  pass "the old piabazzite interface disappeared during the switch"
else
  warn "the interface transition was too fast to observe"
fi

if (( NEW_ENDPOINT_ADDED == 1 )); then
  pass "a different WireGuard endpoint was observed"
else
  fail "no different WireGuard endpoint was observed before the timeout"
fi

if [[ -n "$NEW_PROFILE_UUID" && "$NEW_PROFILE_UUID" != "$OLD_PROFILE_UUID" ]]; then
  pass "NetworkManager created a new WireGuard profile UUID"
elif [[ -n "$NEW_PROFILE_UUID" ]]; then
  warn "NetworkManager reused the previous profile UUID"
else
  fail "the active post-switch NetworkManager profile could not be read"
fi

if [[ -n "$NEW_FWMARK" && "$NEW_FWMARK" != "off" ]]; then
  pass "the new WireGuard fwmark is available"
  printf 'New fwmark: %s\n' "$NEW_FWMARK"
  if [[ "$NEW_FWMARK" == "$OLD_FWMARK" ]]; then
    pass "NetworkManager reused the WireGuard fwmark across the switch"
  else
    pass "NetworkManager assigned a new valid fwmark to the replacement profile"
  fi
else
  fail "the new WireGuard fwmark is unavailable"
fi

if (( SWITCH_SUCCESS == 1 )); then
  pass "the new WireGuard server completed a fresh handshake under protection"
else
  fail "the new server did not complete a fresh handshake before the timeout"
fi

if [[ "$NEW_ENDPOINT_FAMILY" == "IPv4" ]]; then
  NEW_ROUTE_LINE="$(
    ip -4 route get "$NEW_ENDPOINT_IP" mark "$NEW_FWMARK" 2>/dev/null \
      | head -n 1
  )"
else
  NEW_ROUTE_LINE="$(
    ip -6 route get "$NEW_ENDPOINT_IP" mark "$NEW_FWMARK" 2>/dev/null \
      | head -n 1
  )"
fi

NEW_ROUTE_DEVICE="$(
  awk '{
    for (i = 1; i <= NF; i++) {
      if ($i == "dev" && i < NF) {
        print $(i + 1)
        exit
      }
    }
  }' <<<"$NEW_ROUTE_LINE"
)"

if [[ -n "$NEW_ROUTE_DEVICE" && "$NEW_ROUTE_DEVICE" != "$VPN_INTERFACE" ]]; then
  pass "the replacement endpoint has a physical route via $NEW_ROUTE_DEVICE"
else
  fail "the replacement endpoint physical route is unknown or unsafe"
fi

if (( SWITCH_SUCCESS == 0 )); then
  printf '\nThe switch did not finish in time. Removing the test firewall table now.\n'
  exit 1
fi

printf '\n%s\n' '--- Verify the new server and retire the old endpoint ---'
expect_success \
  "public IPv4 connectivity works through the new PIA server" \
  tcp_probe 4 1.1.1.1 443 5

if vpn_is_active; then
  pass "piabazzite is active after the server switch"
else
  fail "piabazzite is not active after the server switch"
fi

if delete_endpoint \
    "$OLD_ENDPOINT_FAMILY" \
    "$OLD_ENDPOINT_IP" \
    "$OLD_ENDPOINT_PORT"; then
  pass "the old PIA endpoint was removed from the allow set"
else
  fail "the old PIA endpoint could not be removed from the allow set"
fi

if set_contains_endpoint \
    "$OLD_ENDPOINT_FAMILY" \
    "$OLD_ENDPOINT_IP" \
    "$OLD_ENDPOINT_PORT"; then
  fail "the retired old endpoint is still present in the allow set"
else
  pass "the retired old endpoint is absent from the allow set"
fi

if set_contains_endpoint \
    "$NEW_ENDPOINT_FAMILY" \
    "$NEW_ENDPOINT_IP" \
    "$NEW_ENDPOINT_PORT"; then
  pass "the active new endpoint remains present in the allow set"
else
  fail "the active new endpoint is missing from the allow set"
fi

BLOCK_BEFORE="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE" =~ ^[0-9]+$ ]] || BLOCK_BEFORE=0

if [[ "$OLD_ENDPOINT_FAMILY" == "IPv4" ]]; then
  OLD_PROBE_FAMILY=4
else
  OLD_PROBE_FAMILY=6
fi

if marked_physical_udp_probe \
    "$OLD_PROBE_FAMILY" \
    "$OLD_ENDPOINT_IP" \
    "$OLD_ENDPOINT_PORT" \
    "$NEW_ROUTE_DEVICE" \
    "$NEW_FWMARK"; then
  pass "a forced physical probe to the retired endpoint was attempted"
else
  fail "the forced physical probe to the retired endpoint could not be created"
fi

sleep 0.25
BLOCK_AFTER="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER" =~ ^[0-9]+$ ]] || BLOCK_AFTER=0

if (( BLOCK_AFTER > BLOCK_BEFORE )); then
  pass "the retired endpoint is blocked on the physical route (${BLOCK_BEFORE} -> ${BLOCK_AFTER})"
else
  fail "the retired endpoint did not reach the physical-route block rule"
fi

if [[ "$NEW_ENDPOINT_FAMILY" == "IPv4" ]]; then
  NEW_PROBE_FAMILY=4
  NEW_ALLOW_COMMENT="allowed endpoint IPv4"
else
  NEW_PROBE_FAMILY=6
  NEW_ALLOW_COMMENT="allowed endpoint IPv6"
fi

ALLOW_BEFORE="$(rule_packets "$NEW_ALLOW_COMMENT")"
[[ "$ALLOW_BEFORE" =~ ^[0-9]+$ ]] || ALLOW_BEFORE=0

if marked_physical_udp_probe \
    "$NEW_PROBE_FAMILY" \
    "$NEW_ENDPOINT_IP" \
    "$NEW_ENDPOINT_PORT" \
    "$NEW_ROUTE_DEVICE" \
    "$NEW_FWMARK"; then
  pass "a forced physical probe to the active endpoint was attempted"
else
  fail "the forced physical probe to the active endpoint could not be created"
fi

sleep 0.25
ALLOW_AFTER="$(rule_packets "$NEW_ALLOW_COMMENT")"
[[ "$ALLOW_AFTER" =~ ^[0-9]+$ ]] || ALLOW_AFTER=0

if (( ALLOW_AFTER > ALLOW_BEFORE )); then
  pass "the active endpoint remains allowed on the physical route"
else
  fail "the active endpoint did not reach its physical-route allow rule"
fi

if (( FIREWALLD_WAS_ACTIVE == 1 )) \
    && systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld remained active throughout the server switch"
else
  warn "firewalld is no longer active"
fi

printf '\n%s\n' '--- Counters before cleanup ---'
sudo -n nft list chain inet "$TABLE" "$CHAIN" 2>/dev/null \
  | sed -E \
      -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/x.x.x.x/g' \
      -e 's/[0-9a-fA-F]{0,4}:[0-9a-fA-F:]+/x::x/g' \
  || true

printf '\n%s\n' '--- Deliberate cleanup ---'
remove_test_table

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "the temporary server-switch table still exists after cleanup"
else
  pass "the temporary server-switch table was removed"
fi

cancel_reset_timer
if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer" 2>/dev/null; then
  fail "the automatic reset timer is still active"
else
  pass "the automatic reset timer was cancelled"
fi

if vpn_is_active; then
  pass "PIA Bazzite is connected to the new server at the end"
else
  fail "PIA Bazzite is not connected at the end"
fi

printf '\n%s\n' '--- Result ---'
printf 'Passed: %d\n' "$PASSED"
printf 'Warnings: %d\n' "$WARNINGS"
printf 'Failures: %d\n' "$FAILURES"

if (( FAILURES == 0 )); then
  printf '\nALL GUARDED SERVER-SWITCH TESTS PASSED\n'
  printf 'PIA Bazzite changed WireGuard servers while fallback traffic remained blocked.\n'
  printf 'The new endpoint was admitted, the old endpoint was retired, and the\n'
  printf 'temporary nftables table was removed afterward.\n'
  exit 0
fi

printf '\nGUARDED SERVER-SWITCH TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'Do not use this prototype as a real kill switch yet.\n'
exit 1
