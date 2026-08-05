#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-networkmanager-restart-test.txt}"

TABLE="pia_bazzite_killswitch_nm_restart_test"
CHAIN="output"
SET4="allowed_endpoints_v4"
SET6="allowed_endpoints_v6"
RESET_UNIT="pia-bazzite-killswitch-nm-restart-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=300

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
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""

NFT_BIN="$(command -v nft || true)"
NMCLI_BIN="$(command -v nmcli || true)"
SYSTEMCTL_BIN="$(command -v systemctl || true)"
BASH_BIN="$(command -v bash || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-nm-restart.XXXXXX.nft)"

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

wifi_is_connected() {
  nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null \
    | awk -F: -v wanted="$WIFI_DEVICE" '
        $1 == wanted && $2 == "wifi" && $3 == "connected" {
          found = 1
        }
        END {
          exit found ? 0 : 1
        }
      '
}

wifi_has_ipv4() {
  ip -4 address show dev "$WIFI_DEVICE" scope global 2>/dev/null \
    | grep -q 'inet '
}

wifi_has_default_route() {
  ip -4 route show default dev "$WIFI_DEVICE" 2>/dev/null \
    | grep -q '^default '
}

wait_for_networkmanager() {
  local attempt

  for attempt in $(seq 1 45); do
    if systemctl is-active --quiet NetworkManager \
        && nmcli general status >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_wifi_ready() {
  local attempt

  for attempt in $(seq 1 100); do
    if wifi_is_connected && wifi_has_ipv4 && wifi_has_default_route; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_vpn_down() {
  local attempt

  for attempt in $(seq 1 40); do
    if ! vpn_is_active; then
      return 0
    fi
    sleep 1
  done
  return 1
}

current_handshake() {
  sudo -n wg show "$VPN_INTERFACE" latest-handshakes 2>/dev/null \
    | awk 'NF >= 2 {
        print $2
        exit
      }'
}

wait_for_recent_handshake() {
  local attempt timestamp now age

  for attempt in $(seq 1 80); do
    if vpn_is_active; then
      timestamp="$(current_handshake)"
      if [[ "$timestamp" =~ ^[0-9]+$ ]] && (( timestamp > 0 )); then
        now="$(date +%s)"
        age=$((now - timestamp))
        if (( age >= 0 && age <= 35 )); then
          return 0
        fi
      fi
    fi
    sleep 1
  done
  return 1
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

  sudo -n python3 - "$family" "$address" "$port" "$device" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text, device = sys.argv[1:5]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

with socket.socket(family, socket.SOCK_STREAM) as sock:
    sock.settimeout(2.0)
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

  sudo -n python3 - "$device" <<'PY'
from __future__ import annotations

import random
import socket
import struct
import sys

device = sys.argv[1]
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

transaction_id = random.randint(0, 65535)
query = (
    struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    + b"\x07example\x03com\x00"
    + struct.pack("!HH", 1, 1)
)

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)
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

if len(response) < 12:
    raise SystemExit(1)

response_id = struct.unpack("!H", response[:2])[0]
raise SystemExit(0 if response_id == transaction_id else 1)
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
  if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
    sudo -n nft delete table inet "$TABLE" >/dev/null 2>&1 || true
  fi
  TABLE_CREATED=0
}

restore_wifi() {
  if [[ -z "$WIFI_UUID" || -z "$WIFI_DEVICE" ]] \
      || (wifi_is_connected && wifi_has_ipv4 && wifi_has_default_route); then
    return
  fi

  nmcli radio wifi on >/dev/null 2>&1 || true
  timeout 110s nmcli connection up uuid "$WIFI_UUID" \
    ifname "$WIFI_DEVICE" >/dev/null 2>&1 || true
}

restore_vpn() {
  if [[ -z "$VPN_UUID" ]] || vpn_is_active \
      || ! wifi_is_connected || ! wifi_has_default_route; then
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

  if ! systemctl is-active --quiet NetworkManager; then
    sudo -n systemctl start NetworkManager >/dev/null 2>&1 || true
    sleep 3
  fi

  restore_wifi
  restore_vpn
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe NetworkManager restart test exited early.\n'
    printf 'Its temporary firewall table and safety timer were removed.\n'
    printf 'NetworkManager, Wi-Fi, and PIA were restored where possible.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded NetworkManager restart kill-switch test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test restarts the complete NetworkManager service while an independent' \
  'nftables kill-switch table remains active.' \
  '' \
  'The PIA endpoint is withheld before the restart. After Wi-Fi returns,' \
  'ordinary physical IPv4, IPv6, and direct DNS must remain blocked.' \
  'The endpoint is then restored and WireGuard must reconnect.' \
  '' \
  'The network will be unavailable temporarily. Do not interact with Plasma' \
  'networking or PIA Bazzite while the test is running.' \
  '' \
  "A root-owned safety unit removes the table and restores NetworkManager," \
  "Wi-Fi, and PIA after ${RESET_SECONDS} seconds." \
  '' \
  'Emergency command after NetworkManager returns:' \
  "  sudo nft delete table inet ${TABLE}"

read -r -p 'Type NETWORK exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "NETWORK" ]]; then
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
  printf 'Required commands are missing. Nothing was changed.\n'
  exit 1
fi

if ! sudo -v; then
  fail "sudo authorization failed"
  exit 1
fi
pass "temporary sudo authorization is available"

if ! systemctl is-active --quiet NetworkManager; then
  fail "NetworkManager is not active before the test"
  exit 1
fi
pass "NetworkManager is active"

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

WIFI_DEVICE="$(
  awk '{
    for (i = 1; i <= NF; i++) {
      if ($i == "dev" && i < NF) {
        print $(i + 1)
        exit
      }
    }
  }' <<<"$ROUTE_LINE"
)"

if [[ -z "$WIFI_DEVICE" || "$WIFI_DEVICE" == "$VPN_INTERFACE" ]]; then
  fail "the physical route to the endpoint is unsafe or unknown"
  exit 1
fi

DEVICE_TYPE="$(
  nmcli -g GENERAL.TYPE device show "$WIFI_DEVICE" 2>/dev/null \
    | head -n 1
)"
if [[ "$DEVICE_TYPE" != "wifi" ]]; then
  fail "the active physical route is not Wi-Fi; it uses $WIFI_DEVICE"
  exit 1
fi
pass "the PIA endpoint uses Wi-Fi device $WIFI_DEVICE"

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
printf 'Wi-Fi profile: %s\n' "${WIFI_NAME:-unknown}"

if ! wifi_is_connected || ! wifi_has_ipv4 || ! wifi_has_default_route; then
  fail "Wi-Fi is not fully ready before the test"
  exit 1
fi
pass "Wi-Fi has an IPv4 address and default route"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous NetworkManager restart test table already exists"
  exit 1
fi
pass "no previous NetworkManager restart table exists"

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 works through the VPN before the restart"
else
  fail "public IPv4 does not work before the restart"
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

    ip protocol udp udp sport 68 udp dport 67 \
      oifname "$WIFI_DEVICE" counter accept comment "DHCPv4"

    ip6 nexthdr udp udp sport 546 udp dport 547 \
      oifname "$WIFI_DEVICE" counter accept comment "DHCPv6"

    ip6 nexthdr icmpv6 icmpv6 type {
      nd-router-solicit,
      nd-neighbor-solicit,
      nd-neighbor-advert
    } oifname "$WIFI_DEVICE" counter accept comment "IPv6 link maintenance"

    ip daddr . udp dport @$SET4 \
      oifname "$WIFI_DEVICE" counter accept comment "allowed endpoint IPv4"

    ip6 daddr . udp dport @$SET6 \
      oifname "$WIFI_DEVICE" counter accept comment "allowed endpoint IPv6"

    oifname "$VPN_INTERFACE" counter accept comment "VPN tunnel"

    counter reject with icmpx type admin-prohibited \
      comment "block outside VPN"
  }
}
NFT

if sudo -n nft -f "$TMP_RULESET"; then
  TABLE_CREATED=1
  pass "the temporary NetworkManager restart table was installed"
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

printf '\n%s\n' '--- Arm independent root-owned safety recovery ---'

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
      "$1" delete table inet pia_bazzite_killswitch_nm_restart_test \
        >/dev/null 2>&1 || true
      "$2" restart NetworkManager >/dev/null 2>&1 || true
      sleep 5
      "$3" radio wifi on >/dev/null 2>&1 || true
      "$3" connection up uuid "$4" ifname "$5" \
        >/dev/null 2>&1 || true
      sleep 8
      "$3" connection up uuid "$6" >/dev/null 2>&1 || true
    ' bash \
    "$NFT_BIN" "$SYSTEMCTL_BIN" "$NMCLI_BIN" \
    "$WIFI_UUID" "$WIFI_DEVICE" "$VPN_UUID"; then
  RESET_SCHEDULED=1
else
  fail "the automatic safety recovery timer could not be created"
  exit 1
fi

if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  pass "automatic safety recovery is armed for ${RESET_SECONDS} seconds"
else
  fail "the automatic safety recovery timer is not active"
  exit 1
fi

printf '\n%s\n' '--- Prepare the blocked restart state ---'

if delete_endpoint; then
  pass "the PIA endpoint was removed from the allow set"
else
  fail "the PIA endpoint could not be removed"
fi

if endpoint_is_present; then
  fail "the PIA endpoint is still present in the allow set"
else
  pass "the endpoint allow set is empty"
fi

timeout 40s nmcli connection down uuid "$VPN_UUID" >/dev/null 2>&1 || true

if wait_for_vpn_down; then
  pass "PIA WireGuard is down before restarting NetworkManager"
else
  fail "PIA WireGuard did not go down before the restart"
fi

BLOCK_BEFORE="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE" =~ ^[0-9]+$ ]] || BLOCK_BEFORE=0

printf '\n%s\n' '--- Restart NetworkManager completely ---'
printf 'Network connectivity will disappear temporarily.\n'

if sudo -n systemctl restart NetworkManager; then
  pass "systemd accepted the complete NetworkManager restart"
else
  fail "NetworkManager restart returned an error"
fi

if wait_for_networkmanager; then
  pass "NetworkManager returned to the active state"
else
  fail "NetworkManager did not return within 45 seconds"
  exit 1
fi

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  pass "the independent kill-switch table survived the NetworkManager restart"
else
  fail "the kill-switch table disappeared during the NetworkManager restart"
  exit 1
fi

if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  pass "the root-owned safety timer survived the NetworkManager restart"
else
  fail "the safety timer disappeared during the NetworkManager restart"
fi

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld is active after the NetworkManager restart"
else
  warn "firewalld is not active after the NetworkManager restart"
fi

printf '\n%s\n' '--- Restore only the original Wi-Fi under protection ---'

nmcli radio wifi on >/dev/null 2>&1 || true
if ! wait_for_wifi_ready; then
  if timeout 110s nmcli connection up uuid "$WIFI_UUID" \
      ifname "$WIFI_DEVICE" >/dev/null 2>&1; then
    pass "NetworkManager explicitly reactivated the original Wi-Fi profile"
  else
    fail "NetworkManager could not reactivate the original Wi-Fi profile"
  fi
fi

if wait_for_wifi_ready; then
  pass "Wi-Fi has an IPv4 address and default route after the restart"
else
  fail "Wi-Fi did not recover after the NetworkManager restart"
  exit 1
fi

CURRENT_WIFI_NAME="$(
  nmcli -g GENERAL.CONNECTION device show "$WIFI_DEVICE" 2>/dev/null \
    | head -n 1
)"
if [[ "$CURRENT_WIFI_NAME" == "$WIFI_NAME" ]]; then
  pass "the original Wi-Fi profile is active after the restart"
else
  fail "active Wi-Fi is '$CURRENT_WIFI_NAME', expected '$WIFI_NAME'"
fi

if endpoint_is_present; then
  fail "the withheld PIA endpoint reappeared unexpectedly"
else
  pass "the PIA endpoint remains withheld after the NetworkManager restart"
fi

printf '\n%s\n' '--- Verify the protected post-restart gap ---'

GAP_BEFORE="$(rule_packets "block outside VPN")"
[[ "$GAP_BEFORE" =~ ^[0-9]+$ ]] || GAP_BEFORE=0

forced_tcp_probe 4 1.1.1.1 443 "$WIFI_DEVICE" \
  >/dev/null 2>&1 || true
pass "a forced physical IPv4 probe was attempted"

if forced_tcp_probe 6 2606:4700:4700::1111 443 \
    "$WIFI_DEVICE" >/dev/null 2>&1; then
  fail "forced physical IPv6 unexpectedly connected"
else
  pass "forced physical IPv6 did not connect"
fi

if dns_response_probe "$WIFI_DEVICE" >/dev/null 2>&1; then
  fail "a valid direct DNS response escaped after the restart"
else
  pass "no valid direct DNS response escaped after the restart"
fi

if tcp_probe 4 1.1.1.1 443 4 >/dev/null 2>&1; then
  fail "ordinary public IPv4 unexpectedly succeeded before VPN recovery"
else
  pass "ordinary public IPv4 remains unavailable before VPN recovery"
fi

sleep 0.5

GAP_AFTER="$(rule_packets "block outside VPN")"
[[ "$GAP_AFTER" =~ ^[0-9]+$ ]] || GAP_AFTER=0

if (( GAP_AFTER >= GAP_BEFORE + 3 )); then
  pass "the block counter confirms protected post-restart traffic (${GAP_BEFORE} -> ${GAP_AFTER})"
else
  fail "the block counter did not increase enough (${GAP_BEFORE} -> ${GAP_AFTER})"
fi

printf '\n%s\n' '--- Restore WireGuard under protection ---'

if add_endpoint; then
  pass "the PIA endpoint was restored to the allow set"
else
  fail "the PIA endpoint could not be restored"
fi

if endpoint_is_present; then
  pass "the PIA endpoint is present in the allow set"
else
  fail "the PIA endpoint is missing from the allow set"
fi

if timeout 90s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1; then
  pass "NetworkManager reactivated the saved PIA WireGuard profile"
else
  fail "NetworkManager could not reactivate the PIA WireGuard profile"
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake after the NetworkManager restart"
else
  fail "WireGuard did not complete a fresh handshake after the restart"
fi

if tcp_probe 4 1.1.1.1 443 6 >/dev/null 2>&1; then
  pass "public IPv4 connectivity returned through the restored VPN"
else
  fail "public IPv4 connectivity did not return through the VPN"
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

if systemctl is-active --quiet NetworkManager; then
  pass "NetworkManager is active at the end"
else
  fail "NetworkManager is not active at the end"
fi

if wifi_is_connected && wifi_has_ipv4 && wifi_has_default_route; then
  pass "the original Wi-Fi is fully connected at the end"
else
  fail "Wi-Fi is not fully connected at the end"
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
  printf '\nALL NETWORKMANAGER RESTART TESTS PASSED\n'
  printf 'The independent kill-switch table survived a complete NetworkManager\n'
  printf 'restart, physical fallback traffic remained blocked after Wi-Fi recovery,\n'
  printf 'and WireGuard completed a fresh handshake after endpoint restoration.\n'
  exit 0
fi

printf '\nNETWORKMANAGER RESTART TEST FAILED\n'
printf 'The temporary table and safety timer were removed during cleanup.\n'
printf 'NetworkManager, Wi-Fi, and PIA were restored where possible.\n'
exit 1
