#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-wifi-lan-switch-test.txt}"

TABLE="pia_bazzite_killswitch_wifi_lan_test"
CHAIN="output"
SET4="allowed_endpoints_v4"
SET6="allowed_endpoints_v6"
RESET_UNIT="pia-bazzite-killswitch-wifi-lan-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=600

PASSED=0
WARNINGS=0
FAILURES=0
TABLE_CREATED=0
RESET_SCHEDULED=0
CLEANUP_RUNNING=0

VPN_UUID=""
VPN_NAME=""
WIFI_UUID=""
WIFI_NAME=""
WIFI_DEVICE=""
ETH_UUID=""
ETH_NAME=""
ETH_DEVICE=""
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""
FWMARK=""

NFT_BIN="$(command -v nft || true)"
NMCLI_BIN="$(command -v nmcli || true)"
BASH_BIN="$(command -v bash || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-wifi-lan.XXXXXX.nft)"

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

device_connected() {
  local device="$1"

  nmcli -t -f DEVICE,STATE device status 2>/dev/null \
    | awk -F: -v wanted="$device" '
        $1 == wanted && $2 == "connected" {
          found = 1
        }
        END {
          exit found ? 0 : 1
        }
      '
}

device_has_ipv4() {
  local device="$1"

  ip -4 address show dev "$device" scope global 2>/dev/null \
    | grep -q 'inet '
}

device_has_default_route() {
  local device="$1"

  ip -4 route show default dev "$device" 2>/dev/null \
    | grep -q '^default '
}

wait_for_device_ready() {
  local device="$1"
  local attempt

  for attempt in $(seq 1 100); do
    if device_connected "$device" \
        && device_has_ipv4 "$device" \
        && device_has_default_route "$device"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_device_down() {
  local device="$1"
  local attempt

  for attempt in $(seq 1 45); do
    if ! device_connected "$device" \
        && ! device_has_ipv4 "$device" \
        && ! device_has_default_route "$device"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

current_endpoint_raw() {
  sudo -n wg show "$VPN_INTERFACE" endpoints 2>/dev/null \
    | awk 'NF >= 2 {
        print $2
        exit
      }'
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

set_endpoint_values() {
  ENDPOINT_IP="$PARSED_IP"
  ENDPOINT_PORT="$PARSED_PORT"
  ENDPOINT_FAMILY="$PARSED_FAMILY"
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

forced_tcp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"
  local device="$4"
  local fwmark="$5"

  sudo -n python3 - \
    "$family" "$address" "$port" "$device" "$fwmark" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text, device, mark_text = sys.argv[1:6]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET
so_mark = getattr(socket, "SO_MARK", 36)
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

with socket.socket(family, socket.SOCK_STREAM) as sock:
    sock.settimeout(2.0)
    sock.setsockopt(socket.SOL_SOCKET, so_mark, int(mark_text, 0))
    sock.setsockopt(
        socket.SOL_SOCKET,
        so_bindtodevice,
        device.encode("utf-8") + b"\0",
    )
    try:
        sock.connect((address, int(port_text)))
    except OSError:
        raise SystemExit(1)
PY
}

dns_response_probe() {
  local device="$1"
  local fwmark="$2"

  sudo -n python3 - "$device" "$fwmark" <<'PY'
from __future__ import annotations

import os
import random
import socket
import struct
import sys

device, mark_text = sys.argv[1:3]
so_mark = getattr(socket, "SO_MARK", 36)
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

transaction_id = random.randint(0, 65535)
header = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
question = (
    b"\x07example\x03com\x00"
    + struct.pack("!HH", 1, 1)
)
query = header + question

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)
    sock.setsockopt(socket.SOL_SOCKET, so_mark, int(mark_text, 0))
    sock.setsockopt(
        socket.SOL_SOCKET,
        so_bindtodevice,
        device.encode("utf-8") + b"\0",
    )

    try:
        sock.sendto(query, ("1.1.1.1", 53))
        response, _ = sock.recvfrom(4096)
    except OSError:
        raise SystemExit(1)

if len(response) >= 12:
    response_id = struct.unpack("!H", response[:2])[0]
    if response_id == transaction_id:
        raise SystemExit(0)

raise SystemExit(1)
PY
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

route_device_for_endpoint() {
  local fwmark route_line

  fwmark="$(
    sudo -n wg show "$VPN_INTERFACE" fwmark 2>/dev/null \
      | head -n 1
  )"

  if [[ -z "$fwmark" || "$fwmark" == "off" ]]; then
    fwmark="$FWMARK"
  fi

  if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
    route_line="$(
      ip -4 route get "$ENDPOINT_IP" mark "$fwmark" 2>/dev/null \
        | head -n 1
    )"
  else
    route_line="$(
      ip -6 route get "$ENDPOINT_IP" mark "$fwmark" 2>/dev/null \
        | head -n 1
    )"
  fi

  awk '{
    for (i = 1; i <= NF; i++) {
      if ($i == "dev" && i < NF) {
        print $(i + 1)
        exit
      }
    }
  }' <<<"$route_line"
}

wait_for_endpoint_route() {
  local expected="$1"
  local attempt current

  for attempt in $(seq 1 75); do
    current="$(route_device_for_endpoint)"
    if [[ "$current" == "$expected" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_fresh_handshake_since() {
  local since="$1"
  local attempt timestamp

  for attempt in $(seq 1 80); do
    timestamp="$(
      sudo -n wg show "$VPN_INTERFACE" latest-handshakes 2>/dev/null \
        | awk 'NF >= 2 {
            print $2
            exit
          }'
    )"

    if [[ "$timestamp" =~ ^[0-9]+$ ]] \
        && (( timestamp >= since )); then
      return 0
    fi

    sleep 1
  done
  return 1
}

refresh_endpoint_if_changed() {
  local raw

  raw="$(current_endpoint_raw)"
  if [[ -z "$raw" ]] || ! parse_endpoint "$raw"; then
    return 0
  fi

  if [[ "$PARSED_IP" == "$ENDPOINT_IP" \
      && "$PARSED_PORT" == "$ENDPOINT_PORT" \
      && "$PARSED_FAMILY" == "$ENDPOINT_FAMILY" ]]; then
    return 0
  fi

  set_endpoint_values
  if add_endpoint; then
    pass "a replacement PIA endpoint was added during the physical-network switch"
  else
    fail "a replacement PIA endpoint could not be added"
    return 1
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

restore_wifi() {
  if [[ -z "$WIFI_UUID" || -z "$WIFI_DEVICE" ]] \
      || (device_connected "$WIFI_DEVICE" \
          && device_has_ipv4 "$WIFI_DEVICE" \
          && device_has_default_route "$WIFI_DEVICE"); then
    return
  fi

  nmcli radio wifi on >/dev/null 2>&1 || true
  timeout 110s nmcli connection up uuid "$WIFI_UUID" \
    ifname "$WIFI_DEVICE" >/dev/null 2>&1 || true
}

restore_vpn() {
  if [[ -z "$VPN_UUID" ]] || vpn_is_active \
      || ! device_connected "$WIFI_DEVICE"; then
    return
  fi

  timeout 90s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1 || true
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
  restore_wifi
  restore_vpn
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe Wi-Fi/LAN switch test exited early.\n'
    printf 'Its temporary firewall table and safety timer were removed.\n'
    printf 'Wi-Fi and PIA were restored where possible.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded Wi-Fi to LAN and back kill-switch test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test starts with Wi-Fi as the physical VPN route.' \
  'It activates the connected Ethernet interface, disconnects Wi-Fi, verifies' \
  'WireGuard over LAN, restores Wi-Fi, then disconnects Ethernet and verifies' \
  'WireGuard over Wi-Fi again.' \
  '' \
  'Exact PIA endpoint traffic is allowed on both physical interfaces.' \
  'All other physical IPv4, IPv6, and DNS traffic must remain blocked.' \
  '' \
  'The test ends with Wi-Fi and PIA connected and Ethernet disconnected, so the' \
  'temporary cable can be unplugged immediately afterward.' \
  '' \
  "A root-owned safety unit removes the table and restores Wi-Fi/PIA after" \
  "${RESET_SECONDS} seconds."

read -r -p 'Type LANBOSS exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "LANBOSS" ]]; then
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

ENDPOINT_RAW="$(current_endpoint_raw)"
if ! parse_endpoint "$ENDPOINT_RAW"; then
  fail "the current WireGuard endpoint could not be parsed"
  exit 1
fi
set_endpoint_values
pass "the current numeric WireGuard endpoint was detected"

FWMARK="$(
  sudo -n wg show "$VPN_INTERFACE" fwmark 2>/dev/null \
    | head -n 1
)"
if [[ -z "$FWMARK" || "$FWMARK" == "off" ]]; then
  fail "the current WireGuard fwmark is unavailable"
  exit 1
fi
pass "the current WireGuard fwmark is available"

WIFI_DEVICE="$(route_device_for_endpoint)"
if [[ -z "$WIFI_DEVICE" ]]; then
  fail "the current physical endpoint route could not be determined"
  exit 1
fi

WIFI_TYPE="$(
  nmcli -g GENERAL.TYPE device show "$WIFI_DEVICE" 2>/dev/null \
    | head -n 1
)"
if [[ "$WIFI_TYPE" != "wifi" ]]; then
  fail "the starting PIA endpoint route is not Wi-Fi; it uses $WIFI_DEVICE"
  printf '%s\n' \
    'Disconnect Ethernet once, reconnect PIA Bazzite, then run this test again.'
  exit 1
fi
pass "the starting PIA endpoint route uses Wi-Fi device $WIFI_DEVICE"

WIFI_UUID="$(
  nmcli -t -f UUID,DEVICE,TYPE connection show --active 2>/dev/null \
    | awk -F: -v wanted="$WIFI_DEVICE" '
        $2 == wanted && ($3 == "802-11-wireless" || $3 == "wifi") {
          print $1
          exit
        }
      '
)"
if [[ -z "$WIFI_UUID" ]]; then
  fail "the active Wi-Fi profile UUID could not be determined"
  exit 1
fi

WIFI_NAME="$(
  nmcli -g connection.id connection show uuid "$WIFI_UUID" 2>/dev/null \
    | head -n 1
)"
pass "the original Wi-Fi profile was detected"
printf 'Wi-Fi: %s on %s\n' "${WIFI_NAME:-unknown}" "$WIFI_DEVICE"

ETH_DEVICE="$(
  nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null \
    | awk -F: '
        $2 == "ethernet" \
        && $3 != "unavailable" \
        && $3 != "unmanaged" {
          print $1
          exit
        }
      '
)"
if [[ -z "$ETH_DEVICE" ]]; then
  fail "no usable Ethernet device with cable carrier was detected"
  printf 'Check that the LAN cable is fully inserted.\n'
  exit 1
fi
pass "Ethernet device $ETH_DEVICE is available"

# Establish a clean Wi-Fi starting state. If Ethernet auto-connected when the
# cable was inserted, remember its profile and disconnect it temporarily.
if device_connected "$ETH_DEVICE"; then
  ETH_UUID="$(
    nmcli -t -f UUID,DEVICE,TYPE connection show --active 2>/dev/null \
      | awk -F: -v wanted="$ETH_DEVICE" '
          $2 == wanted && $3 == "802-3-ethernet" {
            print $1
            exit
          }
        '
  )"
  ETH_NAME="$(
    nmcli -g connection.id connection show uuid "$ETH_UUID" 2>/dev/null \
      | head -n 1
  )"

  timeout 45s nmcli device disconnect "$ETH_DEVICE" >/dev/null 2>&1 || true
  wait_for_device_down "$ETH_DEVICE" || true
  pass "Ethernet was temporarily disconnected to establish the Wi-Fi baseline"
fi

if ! device_connected "$WIFI_DEVICE" \
    || ! device_has_ipv4 "$WIFI_DEVICE" \
    || ! device_has_default_route "$WIFI_DEVICE"; then
  fail "Wi-Fi is not fully ready at the baseline"
  exit 1
fi
pass "Wi-Fi has an IPv4 address and default route"

if ! wait_for_endpoint_route "$WIFI_DEVICE"; then
  fail "the WireGuard endpoint route did not settle on Wi-Fi"
  exit 1
fi
pass "the WireGuard endpoint route is confirmed on Wi-Fi"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous Wi-Fi/LAN test table already exists"
  exit 1
fi
pass "no previous Wi-Fi/LAN test table exists"

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works through the VPN over Wi-Fi"
else
  fail "public IPv4 connectivity does not work at the baseline"
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
      "$1" delete table inet pia_bazzite_killswitch_wifi_lan_test \
        >/dev/null 2>&1 || true
      "$2" radio wifi on >/dev/null 2>&1 || true
      "$2" connection up uuid "$3" ifname "$4" \
        >/dev/null 2>&1 || true
      sleep 8
      "$2" connection up uuid "$5" >/dev/null 2>&1 || true
    ' bash \
    "$NFT_BIN" "$NMCLI_BIN" "$WIFI_UUID" "$WIFI_DEVICE" "$VPN_UUID"; then
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

printf '\n%s\n' '--- Install the dual-interface kill-switch table ---'

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

    ip protocol udp udp sport 68 udp dport 67 \
      oifname { "$WIFI_DEVICE", "$ETH_DEVICE" } \
      counter accept comment "DHCPv4"

    ip6 nexthdr udp udp sport 546 udp dport 547 \
      oifname { "$WIFI_DEVICE", "$ETH_DEVICE" } \
      counter accept comment "DHCPv6"

    ip6 nexthdr icmpv6 icmpv6 type {
      nd-router-solicit,
      nd-neighbor-solicit,
      nd-neighbor-advert
    } oifname { "$WIFI_DEVICE", "$ETH_DEVICE" } \
      counter accept comment "IPv6 link maintenance"

    ip daddr . udp dport @$SET4 \
      oifname "$WIFI_DEVICE" counter accept comment "endpoint via Wi-Fi"

    ip daddr . udp dport @$SET4 \
      oifname "$ETH_DEVICE" counter accept comment "endpoint via Ethernet"

    ip6 daddr . udp dport @$SET6 \
      oifname "$WIFI_DEVICE" counter accept comment "endpoint6 via Wi-Fi"

    ip6 daddr . udp dport @$SET6 \
      oifname "$ETH_DEVICE" counter accept comment "endpoint6 via Ethernet"

    oifname "$VPN_INTERFACE" counter accept comment "VPN tunnel"

    oifname "$WIFI_DEVICE" counter reject with icmpx type admin-prohibited \
      comment "block Wi-Fi outside VPN"

    oifname "$ETH_DEVICE" counter reject with icmpx type admin-prohibited \
      comment "block Ethernet outside VPN"

    counter reject with icmpx type admin-prohibited \
      comment "block other outside VPN"
  }
}
NFT

if sudo -n nft -f "$TMP_RULESET"; then
  TABLE_CREATED=1
  pass "the dual-interface kill-switch table was installed"
else
  fail "the temporary nftables table could not be installed"
  exit 1
fi

if add_endpoint; then
  pass "the current PIA endpoint was added to the allow set"
else
  fail "the PIA endpoint could not be added"
  exit 1
fi

if endpoint_is_present; then
  pass "the current PIA endpoint is present in the allow set"
else
  fail "the PIA endpoint is missing from the allow set"
fi

printf '\n%s\n' '--- Activate Ethernet under protection ---'

if [[ -n "$ETH_UUID" ]]; then
  if timeout 110s nmcli connection up uuid "$ETH_UUID" \
      ifname "$ETH_DEVICE" >/dev/null 2>&1; then
    pass "NetworkManager activated the existing Ethernet profile"
  else
    fail "NetworkManager could not activate the existing Ethernet profile"
  fi
else
  if timeout 110s nmcli device connect "$ETH_DEVICE" >/dev/null 2>&1; then
    pass "NetworkManager activated Ethernet"
  else
    fail "NetworkManager could not activate Ethernet"
  fi

  ETH_UUID="$(
    nmcli -t -f UUID,DEVICE,TYPE connection show --active 2>/dev/null \
      | awk -F: -v wanted="$ETH_DEVICE" '
          $2 == wanted && $3 == "802-3-ethernet" {
            print $1
            exit
          }
        '
  )"
  ETH_NAME="$(
    nmcli -g connection.id connection show uuid "$ETH_UUID" 2>/dev/null \
      | head -n 1
  )"
fi

if wait_for_device_ready "$ETH_DEVICE"; then
  pass "Ethernet has an IPv4 address and default route"
else
  fail "Ethernet did not become fully ready within 100 seconds"
fi
printf 'Ethernet: %s on %s\n' "${ETH_NAME:-unknown}" "$ETH_DEVICE"

printf '\n%s\n' '--- Switch the physical VPN route from Wi-Fi to Ethernet ---'
SWITCH_TO_ETH_START="$(date +%s)"

if timeout 50s nmcli device disconnect "$WIFI_DEVICE" >/dev/null 2>&1; then
  pass "NetworkManager disconnected the complete Wi-Fi device"
else
  fail "NetworkManager could not disconnect Wi-Fi"
fi

if wait_for_device_down "$WIFI_DEVICE"; then
  pass "Wi-Fi is fully down during the Ethernet phase"
else
  fail "Wi-Fi did not become fully disconnected"
fi

refresh_endpoint_if_changed || true

if ! vpn_is_active; then
  timeout 90s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1 || true
fi

if wait_for_endpoint_route "$ETH_DEVICE"; then
  pass "the WireGuard endpoint route switched to Ethernet"
else
  fail "the WireGuard endpoint route did not switch to Ethernet"
fi

if wait_for_fresh_handshake_since "$SWITCH_TO_ETH_START"; then
  pass "WireGuard completed a fresh handshake over Ethernet"
else
  fail "WireGuard did not complete a fresh handshake over Ethernet"
fi

if tcp_probe 4 1.1.1.1 443 6 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works through the VPN over Ethernet"
else
  fail "public IPv4 connectivity does not work through the VPN over Ethernet"
fi

printf '\n%s\n' '--- Verify no physical Ethernet leak ---'
FWMARK="$(
  sudo -n wg show "$VPN_INTERFACE" fwmark 2>/dev/null \
    | head -n 1
)"
ETH_BLOCK_BEFORE="$(rule_packets "block Ethernet outside VPN")"
[[ "$ETH_BLOCK_BEFORE" =~ ^[0-9]+$ ]] || ETH_BLOCK_BEFORE=0

forced_tcp_probe 4 1.1.1.1 443 "$ETH_DEVICE" "$FWMARK" \
  >/dev/null 2>&1 || true
pass "a forced physical IPv4 probe was attempted over Ethernet"

if forced_tcp_probe 6 2606:4700:4700::1111 443 \
    "$ETH_DEVICE" "$FWMARK" >/dev/null 2>&1; then
  fail "forced physical IPv6 unexpectedly connected over Ethernet"
else
  pass "forced physical IPv6 did not connect over Ethernet"
fi

if dns_response_probe "$ETH_DEVICE" "$FWMARK" >/dev/null 2>&1; then
  fail "a valid direct DNS response escaped over Ethernet"
else
  pass "no valid direct DNS response escaped over Ethernet"
fi

sleep 0.5
ETH_BLOCK_AFTER="$(rule_packets "block Ethernet outside VPN")"
[[ "$ETH_BLOCK_AFTER" =~ ^[0-9]+$ ]] || ETH_BLOCK_AFTER=0

if (( ETH_BLOCK_AFTER >= ETH_BLOCK_BEFORE + 2 )); then
  pass "the Ethernet-specific block counter increased (${ETH_BLOCK_BEFORE} -> ${ETH_BLOCK_AFTER})"
else
  fail "the Ethernet-specific block counter did not increase enough (${ETH_BLOCK_BEFORE} -> ${ETH_BLOCK_AFTER})"
fi

printf '\n%s\n' '--- Restore Wi-Fi, then switch back from Ethernet ---'

nmcli radio wifi on >/dev/null 2>&1 || true
if timeout 115s nmcli connection up uuid "$WIFI_UUID" \
    ifname "$WIFI_DEVICE" >/dev/null 2>&1; then
  pass "NetworkManager restored the original Wi-Fi profile"
else
  fail "NetworkManager could not restore the original Wi-Fi profile"
fi

if wait_for_device_ready "$WIFI_DEVICE"; then
  pass "the original Wi-Fi has an IPv4 address and default route"
else
  fail "the original Wi-Fi did not become fully ready"
fi

SWITCH_TO_WIFI_START="$(date +%s)"

if timeout 50s nmcli device disconnect "$ETH_DEVICE" >/dev/null 2>&1; then
  pass "NetworkManager disconnected the Ethernet device"
else
  fail "NetworkManager could not disconnect Ethernet"
fi

if wait_for_device_down "$ETH_DEVICE"; then
  pass "Ethernet is fully down for the final Wi-Fi phase"
else
  fail "Ethernet did not become fully disconnected"
fi

refresh_endpoint_if_changed || true

if ! vpn_is_active; then
  timeout 90s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1 || true
fi

if wait_for_endpoint_route "$WIFI_DEVICE"; then
  pass "the WireGuard endpoint route switched back to Wi-Fi"
else
  fail "the WireGuard endpoint route did not switch back to Wi-Fi"
fi

if wait_for_fresh_handshake_since "$SWITCH_TO_WIFI_START"; then
  pass "WireGuard completed a fresh handshake after returning to Wi-Fi"
else
  fail "WireGuard did not complete a fresh handshake after returning to Wi-Fi"
fi

if tcp_probe 4 1.1.1.1 443 6 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works through the VPN over Wi-Fi again"
else
  fail "public IPv4 connectivity does not work through the restored VPN"
fi

printf '\n%s\n' '--- Verify no physical Wi-Fi leak ---'
FWMARK="$(
  sudo -n wg show "$VPN_INTERFACE" fwmark 2>/dev/null \
    | head -n 1
)"
WIFI_BLOCK_BEFORE="$(rule_packets "block Wi-Fi outside VPN")"
[[ "$WIFI_BLOCK_BEFORE" =~ ^[0-9]+$ ]] || WIFI_BLOCK_BEFORE=0

forced_tcp_probe 4 1.1.1.1 443 "$WIFI_DEVICE" "$FWMARK" \
  >/dev/null 2>&1 || true
pass "a forced physical IPv4 probe was attempted over Wi-Fi"

if forced_tcp_probe 6 2606:4700:4700::1111 443 \
    "$WIFI_DEVICE" "$FWMARK" >/dev/null 2>&1; then
  fail "forced physical IPv6 unexpectedly connected over Wi-Fi"
else
  pass "forced physical IPv6 did not connect over Wi-Fi"
fi

if dns_response_probe "$WIFI_DEVICE" "$FWMARK" >/dev/null 2>&1; then
  fail "a valid direct DNS response escaped over Wi-Fi"
else
  pass "no valid direct DNS response escaped over Wi-Fi"
fi

sleep 0.5
WIFI_BLOCK_AFTER="$(rule_packets "block Wi-Fi outside VPN")"
[[ "$WIFI_BLOCK_AFTER" =~ ^[0-9]+$ ]] || WIFI_BLOCK_AFTER=0

if (( WIFI_BLOCK_AFTER >= WIFI_BLOCK_BEFORE + 2 )); then
  pass "the Wi-Fi-specific block counter increased (${WIFI_BLOCK_BEFORE} -> ${WIFI_BLOCK_AFTER})"
else
  fail "the Wi-Fi-specific block counter did not increase enough (${WIFI_BLOCK_BEFORE} -> ${WIFI_BLOCK_AFTER})"
fi

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld remained active throughout both physical-network switches"
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

if device_connected "$WIFI_DEVICE" \
    && device_has_ipv4 "$WIFI_DEVICE" \
    && device_has_default_route "$WIFI_DEVICE"; then
  pass "Wi-Fi is fully connected at the end"
else
  fail "Wi-Fi is not fully connected at the end"
fi

if device_connected "$ETH_DEVICE"; then
  fail "Ethernet is still connected at the end"
else
  pass "Ethernet is disconnected and the cable can now be unplugged"
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
  printf '\nALL WI-FI/LAN SWITCH TESTS PASSED\n'
  printf 'WireGuard moved from Wi-Fi to Ethernet and back while exact endpoint\n'
  printf 'traffic remained permitted, ordinary physical IPv4/IPv6/DNS remained\n'
  printf 'blocked, and both transitions completed fresh handshakes.\n'
  printf 'Wi-Fi and PIA are connected; Ethernet is disconnected.\n'
  printf '\nThe temporary LAN cable may now be unplugged.\n'
  exit 0
fi

printf '\nWI-FI/LAN SWITCH TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'Wi-Fi and PIA were restored where possible.\n'
exit 1
