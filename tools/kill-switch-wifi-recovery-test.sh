#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-wifi-recovery-test-v2.txt}"

TABLE="pia_bazzite_killswitch_wifi_test_v2"
CHAIN="output"
SET4="allowed_endpoints_v4"
SET6="allowed_endpoints_v6"
RESET_UNIT="pia-bazzite-killswitch-wifi-test-v2-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=360

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
FWMARK=""

NFT_BIN="$(command -v nft || true)"
NMCLI_BIN="$(command -v nmcli || true)"
BASH_BIN="$(command -v bash || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-wifi-v2.XXXXXX.nft)"

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

forced_physical_probe() {
  local family="$1"
  local protocol="$2"
  local address="$3"
  local port="$4"
  local device="$5"
  local fwmark="$6"

  sudo -n python3 - \
    "$family" "$protocol" "$address" "$port" "$device" "$fwmark" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, protocol, address, port_text, device, mark_text = sys.argv[1:7]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET
sock_type = socket.SOCK_DGRAM if protocol == "udp" else socket.SOCK_STREAM
so_mark = getattr(socket, "SO_MARK", 36)
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

with socket.socket(family, sock_type) as sock:
    sock.settimeout(1.5)
    sock.setsockopt(socket.SOL_SOCKET, so_mark, int(mark_text, 0))
    sock.setsockopt(
        socket.SOL_SOCKET,
        so_bindtodevice,
        device.encode("utf-8") + b"\0",
    )

    try:
        sock.connect((address, int(port_text)))
        if protocol == "udp":
            sock.send(b"PIA-BAZZITE-WIFI-V2-PHYSICAL-PROBE")
    except OSError:
        # An nftables REJECT may fail synchronously. The rule counter below is
        # the authoritative result.
        pass
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

wait_for_wifi_down() {
  local attempt
  for attempt in $(seq 1 35); do
    if ! wifi_is_connected \
        && ! wifi_has_ipv4 \
        && ! wifi_has_default_route; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_wifi_ready() {
  local attempt
  for attempt in $(seq 1 90); do
    if wifi_is_connected && wifi_has_ipv4 && wifi_has_default_route; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_recent_handshake() {
  local attempt timestamp now age
  for attempt in $(seq 1 65); do
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

restore_wifi() {
  if [[ -z "$WIFI_UUID" || -z "$WIFI_DEVICE" ]] \
      || (wifi_is_connected && wifi_has_ipv4 && wifi_has_default_route); then
    return
  fi

  printf '%s\n' \
    'Cleanup: attempting to restore the original Wi-Fi profile ...'
  nmcli radio wifi on >/dev/null 2>&1 || true
  timeout 95s nmcli connection up uuid "$WIFI_UUID" \
    ifname "$WIFI_DEVICE" >/dev/null 2>&1 \
    || warn "automatic Wi-Fi restoration during cleanup did not succeed"
}

restore_vpn() {
  if [[ -z "$VPN_UUID" ]] || vpn_is_active \
      || ! wifi_is_connected || ! wifi_has_default_route; then
    return
  fi

  printf '%s\n' \
    'Cleanup: attempting to restore the PIA WireGuard profile ...'
  timeout 75s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1 \
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
  restore_wifi
  restore_vpn
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe Wi-Fi recovery v2 test exited early.\n'
    printf 'Its temporary firewall table and safety timer were removed.\n'
    printf 'Wi-Fi and PIA were restored where possible.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded Wi-Fi outage and recovery kill-switch test v2\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This corrected test disconnects the complete Wi-Fi DEVICE, not only the' \
  'current profile. NetworkManager therefore cannot jump to another saved WLAN.' \
  '' \
  'During recovery, only the original Wi-Fi profile is explicitly activated.' \
  'The PIA endpoint is temporarily withheld so the VPN cannot return before the' \
  'physical leak checks have completed.' \
  '' \
  "A root-owned safety unit removes the table and restores Wi-Fi/PIA after" \
  "${RESET_SECONDS} seconds." \
  '' \
  'Do not reconnect Wi-Fi manually while the test is running.' \
  'The explicit NetworkManager activation may take up to 90 seconds.' \
  '' \
  'Emergency command in another terminal:' \
  "  sudo nft delete table inet ${TABLE}"

read -r -p 'Type WIFI2 exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "WIFI2" ]]; then
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
  fail "the physical route to the WireGuard endpoint is unsafe or unknown"
  exit 1
fi
pass "the WireGuard endpoint escapes through $WIFI_DEVICE"

DEVICE_TYPE="$(
  nmcli -g GENERAL.TYPE device show "$WIFI_DEVICE" 2>/dev/null \
    | head -n 1
)"
if [[ "$DEVICE_TYPE" != "wifi" ]]; then
  fail "$WIFI_DEVICE is not a Wi-Fi device"
  exit 1
fi
pass "$WIFI_DEVICE is the active Wi-Fi device"

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
  fail "the active Wi-Fi UUID could not be determined"
  exit 1
fi

WIFI_NAME="$(
  nmcli -g connection.id connection show uuid "$WIFI_UUID" 2>/dev/null \
    | head -n 1
)"
pass "the original Wi-Fi profile was detected"
printf 'Wi-Fi profile to restore: %s\n' "${WIFI_NAME:-unknown}"
printf 'Wi-Fi device: %s\n' "$WIFI_DEVICE"

if ! wifi_is_connected || ! wifi_has_ipv4 || ! wifi_has_default_route; then
  fail "Wi-Fi is not fully ready before the test"
  exit 1
fi
pass "Wi-Fi has an IPv4 address and default route"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous Wi-Fi v2 test table already exists"
  exit 1
fi
pass "no previous Wi-Fi v2 test table exists"

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works through the VPN before the outage"
else
  fail "public IPv4 connectivity does not work before the test"
  exit 1
fi

printf '\n%s\n' '--- Schedule the automatic safety recovery ---'

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
      "$1" delete table inet pia_bazzite_killswitch_wifi_test_v2 \
        >/dev/null 2>&1 || true
      "$2" radio wifi on >/dev/null 2>&1 || true
      "$2" connection up uuid "$3" ifname "$4" \
        >/dev/null 2>&1 || true
      sleep 8
      "$2" connection up uuid "$5" \
        >/dev/null 2>&1 || true
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
  pass "temporary Wi-Fi v2 kill-switch table was installed"
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
  pass "IPv4 connectivity still works through piabazzite before Wi-Fi loss"
else
  fail "VPN connectivity failed after installing the test table"
  exit 1
fi

printf '\n%s\n' '--- Disconnect the entire Wi-Fi device ---'
printf 'Disconnecting device %s; other saved WLANs must not activate.\n' \
  "$WIFI_DEVICE"

if timeout 45s nmcli device disconnect "$WIFI_DEVICE" >/dev/null 2>&1; then
  pass "NetworkManager disconnected the complete Wi-Fi device"
else
  fail "NetworkManager could not disconnect the Wi-Fi device"
fi

if wait_for_wifi_down; then
  pass "$WIFI_DEVICE has no Wi-Fi connection, IPv4 address, or default route"
else
  fail "$WIFI_DEVICE did not become fully disconnected within 35 seconds"
fi

ACTIVE_OTHER_WIFI="$(
  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null \
    | awk -F: '$2 == "wifi" && $3 == "connected" {
        print
      }'
)"
if [[ -z "$ACTIVE_OTHER_WIFI" ]]; then
  pass "NetworkManager did not jump to another saved Wi-Fi network"
else
  fail "another Wi-Fi network became active: $ACTIVE_OTHER_WIFI"
fi

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  pass "the kill-switch table remained active during complete Wi-Fi loss"
else
  fail "the kill-switch table disappeared during Wi-Fi loss"
  exit 1
fi

if vpn_is_active; then
  pass "the WireGuard profile remained logically present without physical transport"
else
  pass "the WireGuard profile deactivated with the physical connection"
fi

printf '\n%s\n' '--- Hold back the PIA endpoint before restoring Wi-Fi ---'

if delete_endpoint; then
  pass "the PIA endpoint was temporarily removed from the allow set"
else
  fail "the PIA endpoint could not be removed from the allow set"
fi

if endpoint_is_present; then
  fail "the PIA endpoint is still present in the allow set"
else
  pass "the endpoint allow set is empty during physical recovery"
fi

# Deactivate any stale logical WireGuard profile. With the endpoint withheld,
# the app/NetworkManager cannot race back online during the leak test.
timeout 35s nmcli connection down uuid "$VPN_UUID" >/dev/null 2>&1 || true

printf '\n%s\n' '--- Restore only the original Wi-Fi profile ---'
printf '%s\n' \
  "Activating '${WIFI_NAME:-$WIFI_UUID}' explicitly." \
  'Please do not reconnect manually; this may take up to 90 seconds.'

if timeout 95s nmcli connection up uuid "$WIFI_UUID" \
    ifname "$WIFI_DEVICE" >/dev/null 2>&1; then
  pass "NetworkManager reactivated the original Wi-Fi profile"
else
  fail "NetworkManager could not reactivate the original Wi-Fi profile"
fi

if wait_for_wifi_ready; then
  pass "the original Wi-Fi regained an IPv4 address and default route"
else
  fail "the original Wi-Fi did not become ready within 90 seconds"
fi

CURRENT_WIFI_NAME="$(
  nmcli -g GENERAL.CONNECTION device show "$WIFI_DEVICE" 2>/dev/null \
    | head -n 1
)"
if [[ "$CURRENT_WIFI_NAME" == "$WIFI_NAME" ]]; then
  pass "the restored connection is the original Wi-Fi profile"
else
  fail "the restored Wi-Fi profile is '$CURRENT_WIFI_NAME', expected '$WIFI_NAME'"
fi

DHCP_PACKETS="$(rule_packets "DHCPv4")"
if [[ "$DHCP_PACKETS" =~ ^[0-9]+$ ]] && (( DHCP_PACKETS > 0 )); then
  pass "the DHCPv4 allow rule counted recovery traffic"
else
  pass "Wi-Fi recovered without a new DHCPv4 packet (cached lease reuse)"
fi

printf '\n%s\n' '--- Verify the protected physical-network gap ---'

BLOCK_BEFORE="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE" =~ ^[0-9]+$ ]] || BLOCK_BEFORE=0

forced_physical_probe 4 tcp 1.1.1.1 443 "$WIFI_DEVICE" "$FWMARK"
pass "a forced physical IPv4 probe was attempted"

forced_physical_probe 6 tcp 2606:4700:4700::1111 443 \
  "$WIFI_DEVICE" "$FWMARK"
pass "a forced physical IPv6 probe was attempted"

forced_physical_probe 4 udp 1.1.1.1 53 "$WIFI_DEVICE" "$FWMARK"
pass "a forced physical DNS-like probe was attempted"

sleep 0.5

BLOCK_AFTER="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER" =~ ^[0-9]+$ ]] || BLOCK_AFTER=0

if (( BLOCK_AFTER >= BLOCK_BEFORE + 3 )); then
  pass "all forced physical probes reached the block rule (${BLOCK_BEFORE} -> ${BLOCK_AFTER})"
else
  fail "fewer than three physical probes reached the block rule (${BLOCK_BEFORE} -> ${BLOCK_AFTER})"
fi

if tcp_probe 4 1.1.1.1 443 4 >/dev/null 2>&1; then
  fail "ordinary public IPv4 traffic unexpectedly succeeded before VPN recovery"
else
  pass "ordinary public IPv4 traffic remains unavailable before VPN recovery"
fi

printf '\n%s\n' '--- Release and restore WireGuard under protection ---'

if add_endpoint; then
  pass "the PIA endpoint was restored to the allow set"
else
  fail "the PIA endpoint could not be restored"
fi

if endpoint_is_present; then
  pass "the active PIA endpoint is present in the allow set"
else
  fail "the active PIA endpoint is missing from the allow set"
fi

if vpn_is_active; then
  pass "PIA WireGuard began recovering automatically after endpoint release"
else
  if timeout 75s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1; then
    pass "NetworkManager reactivated the PIA WireGuard profile"
  else
    fail "NetworkManager could not reactivate the PIA WireGuard profile"
  fi
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake after Wi-Fi recovery"
else
  fail "no recent WireGuard handshake appeared within 65 seconds"
fi

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works again through the restored VPN"
else
  fail "public IPv4 connectivity did not return through the VPN"
fi

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld remained active throughout the Wi-Fi cycle"
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
  printf '\nALL WI-FI OUTAGE AND RECOVERY V2 TESTS PASSED\n'
  printf 'The complete Wi-Fi device was disconnected without switching networks,\n'
  printf 'the original profile recovered under protection, forced physical traffic\n'
  printf 'was blocked, and WireGuard completed a fresh handshake afterward.\n'
  printf 'The temporary table and safety timer were removed.\n'
  exit 0
fi

printf '\nWI-FI OUTAGE AND RECOVERY V2 TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'Wi-Fi and PIA were restored where possible.\n'
exit 1
