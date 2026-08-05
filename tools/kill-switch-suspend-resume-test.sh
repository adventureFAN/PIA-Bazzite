#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-suspend-resume-test.txt}"

TABLE="pia_bazzite_killswitch_suspend_test"
CHAIN="output"
SET4="allowed_endpoints_v4"
SET6="allowed_endpoints_v6"
RESET_UNIT="pia-bazzite-killswitch-suspend-test-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=720

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
BASH_BIN="$(command -v bash || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-suspend.XXXXXX.nft)"

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

flush_endpoints() {
  sudo -n nft flush set inet "$TABLE" "$SET4" >/dev/null 2>&1 || true
  sudo -n nft flush set inet "$TABLE" "$SET6" >/dev/null 2>&1 || true
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

forced_physical_probe() {
  local family="$1"
  local protocol="$2"
  local address="$3"
  local port="$4"
  local device="$5"

  sudo -n python3 - \
    "$family" "$protocol" "$address" "$port" "$device" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, protocol, address, port_text, device = sys.argv[1:6]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET
sock_type = socket.SOCK_DGRAM if protocol == "udp" else socket.SOCK_STREAM
so_bindtodevice = getattr(socket, "SO_BINDTODEVICE", 25)

with socket.socket(family, sock_type) as sock:
    sock.settimeout(1.5)
    sock.setsockopt(
        socket.SOL_SOCKET,
        so_bindtodevice,
        device.encode("utf-8") + b"\0",
    )

    try:
        sock.connect((address, int(port_text)))
        if protocol == "udp":
            sock.send(b"PIA-BAZZITE-SUSPEND-PHYSICAL-PROBE")
    except OSError:
        # A local nftables REJECT may fail synchronously. The nftables counter
        # checked afterward is the authoritative result.
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

clock_snapshot() {
  python3 <<'PY'
from __future__ import annotations

import time

print(
    f"{time.clock_gettime(time.CLOCK_BOOTTIME):.6f} "
    f"{time.clock_gettime(time.CLOCK_MONOTONIC):.6f}"
)
PY
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

wait_for_recent_handshake() {
  local attempt timestamp now age
  for attempt in $(seq 1 75); do
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
        if (( age >= 0 && age <= 35 )); then
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
  timeout 105s nmcli connection up uuid "$WIFI_UUID" \
    ifname "$WIFI_DEVICE" >/dev/null 2>&1 \
    || warn "automatic Wi-Fi restoration during cleanup did not succeed"
}

restore_vpn() {
  local current_line current_uuid

  if vpn_is_active || ! wifi_is_connected || ! wifi_has_default_route; then
    return
  fi

  current_line="$(active_vpn_line)"
  current_uuid="${current_line%%:*}"

  if [[ -n "$current_uuid" ]]; then
    VPN_UUID="$current_uuid"
  fi

  if [[ -z "$VPN_UUID" ]]; then
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
  restore_wifi
  restore_vpn
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nThe suspend/resume test exited early.\n'
    printf 'Its temporary firewall table and safety timer were removed.\n'
    printf 'Wi-Fi and PIA were restored where possible.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded suspend/resume kill-switch test v2\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test WILL suspend the computer.' \
  '' \
  'After the screen turns off, wait roughly 20 to 30 seconds and wake the' \
  'computer normally. Log in again if Plasma shows the lock screen.' \
  '' \
  'Do not reconnect Wi-Fi or VPN manually. The script continues automatically' \
  'after resume and may need up to two minutes to restore the network.' \
  '' \
  "A root-owned safety unit removes the test table and restores Wi-Fi/PIA after" \
  "${RESET_SECONDS} active seconds." \
  '' \
  'Emergency command after resume:' \
  "  sudo nft delete table inet ${TABLE}"

read -r -p 'Type SUSPEND exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "SUSPEND" ]]; then
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

SUSPEND_TARGET_STATE="$(
  systemctl show suspend.target     --property=LoadState     --value     2>/dev/null || true
)"

if [[ "$SUSPEND_TARGET_STATE" != "loaded" ]]; then
  fail "systemd suspend.target is not loaded"
  exit 1
fi
pass "systemd suspend.target is loaded"

VPN_LINE="$(active_vpn_line)"
if [[ -z "$VPN_LINE" ]]; then
  fail "PIA Bazzite is not connected"
  exit 1
fi

IFS=: read -r VPN_UUID VPN_NAME VPN_TYPE VPN_DEVICE <<<"$VPN_LINE"
pass "PIA Bazzite WireGuard profile is active"
printf 'VPN profile: %s\n' "$VPN_NAME"

ENDPOINT_RAW="$(current_endpoint_raw)"
if ! parse_endpoint "$ENDPOINT_RAW"; then
  fail "the current numeric WireGuard endpoint could not be parsed"
  exit 1
fi
set_endpoint_values
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
  fail "the physical endpoint route is unsafe or unknown"
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
printf 'Wi-Fi profile: %s\n' "${WIFI_NAME:-unknown}"
printf 'Wi-Fi device: %s\n' "$WIFI_DEVICE"

if ! wifi_is_connected || ! wifi_has_ipv4 || ! wifi_has_default_route; then
  fail "Wi-Fi is not fully ready before suspend"
  exit 1
fi
pass "Wi-Fi has an IPv4 address and default route"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous suspend test table already exists"
  exit 1
fi
pass "no previous suspend test table exists"

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works through the VPN before suspend"
else
  fail "public IPv4 connectivity does not work before suspend"
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
      "$1" delete table inet pia_bazzite_killswitch_suspend_test \
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
  pass "automatic safety recovery is armed for ${RESET_SECONDS} active seconds"
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
  pass "temporary suspend/resume kill-switch table was installed"
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
  pass "VPN connectivity still works with protection active"
else
  fail "VPN connectivity failed after installing the table"
  exit 1
fi

BLOCK_BEFORE_SUSPEND="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE_SUSPEND" =~ ^[0-9]+$ ]] || BLOCK_BEFORE_SUSPEND=0

read -r BOOT_BEFORE MONO_BEFORE < <(clock_snapshot)
WALL_BEFORE="$(date +%s)"

printf '\n%s\n' '--- Suspend the computer ---'
printf '%s\n' \
  'The computer will suspend in 5 seconds.' \
  'Wait around 20 to 30 seconds, then wake it normally.'
sleep 5

if systemctl suspend; then
  pass "systemctl suspend returned after resume"
else
  fail "systemctl suspend returned an error"
  exit 1
fi

WALL_AFTER="$(date +%s)"
read -r BOOT_AFTER MONO_AFTER < <(clock_snapshot)

SUSPEND_METRICS="$(
  python3 - \
    "$BOOT_BEFORE" "$MONO_BEFORE" "$BOOT_AFTER" "$MONO_AFTER" \
    "$WALL_BEFORE" "$WALL_AFTER" <<'PY'
from __future__ import annotations

import sys

boot_before, mono_before, boot_after, mono_after = map(float, sys.argv[1:5])
wall_before, wall_after = map(float, sys.argv[5:7])

boot_delta = boot_after - boot_before
mono_delta = mono_after - mono_before
suspend_estimate = max(0.0, boot_delta - mono_delta)
wall_delta = max(0.0, wall_after - wall_before)

print(f"{boot_delta:.1f} {mono_delta:.1f} {suspend_estimate:.1f} {wall_delta:.1f}")
PY
)"
read -r BOOT_DELTA MONO_DELTA SUSPEND_ESTIMATE WALL_DELTA \
  <<<"$SUSPEND_METRICS"

printf 'Elapsed wall time: %ss\n' "$WALL_DELTA"
printf 'Estimated suspended time: %ss\n' "$SUSPEND_ESTIMATE"

if python3 - "$SUSPEND_ESTIMATE" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) >= 3.0 else 1)
PY
then
  pass "a real suspend interval was detected"
else
  fail "no meaningful suspend interval was detected"
fi

printf '\n%s\n' '--- Verify protection immediately after resume ---'

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  pass "the kill-switch table survived suspend and resume"
else
  fail "the kill-switch table disappeared across suspend"
  exit 1
fi

if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  pass "the automatic safety timer survived suspend"
else
  fail "the automatic safety timer is no longer active"
fi

if systemctl is-active --quiet firewalld 2>/dev/null; then
  pass "firewalld is active after resume"
else
  warn "firewalld is not active after resume"
fi

BLOCK_AFTER_RESUME="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER_RESUME" =~ ^[0-9]+$ ]] || BLOCK_AFTER_RESUME=0
printf 'Block counter across resume: %s -> %s\n' \
  "$BLOCK_BEFORE_SUSPEND" "$BLOCK_AFTER_RESUME"

if wait_for_wifi_ready; then
  pass "Wi-Fi regained an IPv4 address and default route after resume"
else
  printf '%s\n' \
    'Wi-Fi did not recover automatically; activating the original profile.'
  nmcli radio wifi on >/dev/null 2>&1 || true
  if timeout 105s nmcli connection up uuid "$WIFI_UUID" \
      ifname "$WIFI_DEVICE" >/dev/null 2>&1; then
    pass "NetworkManager explicitly restored the original Wi-Fi profile"
  else
    fail "NetworkManager could not restore the original Wi-Fi profile"
  fi

  if wait_for_wifi_ready; then
    pass "Wi-Fi became ready after explicit restoration"
  else
    fail "Wi-Fi is still not ready after explicit restoration"
  fi
fi

CURRENT_WIFI_NAME="$(
  nmcli -g GENERAL.CONNECTION device show "$WIFI_DEVICE" 2>/dev/null \
    | head -n 1
)"
if [[ "$CURRENT_WIFI_NAME" == "$WIFI_NAME" ]]; then
  pass "the original Wi-Fi profile is active after resume"
else
  fail "active Wi-Fi is '$CURRENT_WIFI_NAME', expected '$WIFI_NAME'"
fi

# If the running app or NetworkManager replaced the WireGuard profile during
# resume, discover and admit the replacement endpoint before assessing recovery.
RESUMED_ENDPOINT_RAW="$(current_endpoint_raw)"
if [[ -n "$RESUMED_ENDPOINT_RAW" ]] \
    && parse_endpoint "$RESUMED_ENDPOINT_RAW"; then
  if [[ "$PARSED_IP" != "$ENDPOINT_IP" \
      || "$PARSED_PORT" != "$ENDPOINT_PORT" \
      || "$PARSED_FAMILY" != "$ENDPOINT_FAMILY" ]]; then
    set_endpoint_values
    if add_endpoint; then
      pass "a replacement PIA endpoint was admitted after resume"
    else
      fail "the replacement PIA endpoint could not be admitted"
    fi
  else
    pass "the original PIA endpoint remained configured after resume"
  fi
else
  warn "no WireGuard endpoint was readable immediately after resume"
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake after resume"
else
  warn "WireGuard had not completed a fresh handshake before the controlled gap"
fi

printf '\n%s\n' '--- Create a controlled protected gap after resume ---'

flush_endpoints
pass "all physical PIA endpoint allowances were temporarily removed"

# Stop whichever PIA WireGuard profile is currently active. The endpoint set is
# empty first, so an automatic reconnect cannot escape the protected gap.
while IFS=: read -r active_uuid active_name active_type active_device; do
  if [[ "$active_type" == "wireguard" && "$active_device" == "$VPN_INTERFACE" ]]; then
    VPN_UUID="$active_uuid"
    timeout 40s nmcli connection down uuid "$active_uuid" \
      >/dev/null 2>&1 || true
  fi
done < <(
  nmcli -t -f UUID,NAME,TYPE,DEVICE connection show --active 2>/dev/null
)

sleep 3

BLOCK_BEFORE_GAP="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE_GAP" =~ ^[0-9]+$ ]] || BLOCK_BEFORE_GAP=0

forced_physical_probe 4 tcp 1.1.1.1 443 "$WIFI_DEVICE"
pass "a forced physical IPv4 probe was attempted after resume"

forced_physical_probe 6 tcp 2606:4700:4700::1111 443 "$WIFI_DEVICE"
pass "a forced physical IPv6 probe was attempted after resume"

forced_physical_probe 4 udp 1.1.1.1 53 "$WIFI_DEVICE"
pass "a forced physical DNS-like probe was attempted after resume"

sleep 0.5

BLOCK_AFTER_GAP="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER_GAP" =~ ^[0-9]+$ ]] || BLOCK_AFTER_GAP=0

if (( BLOCK_AFTER_GAP >= BLOCK_BEFORE_GAP + 3 )); then
  pass "all post-resume physical probes reached the block rule (${BLOCK_BEFORE_GAP} -> ${BLOCK_AFTER_GAP})"
else
  fail "fewer than three post-resume probes reached the block rule (${BLOCK_BEFORE_GAP} -> ${BLOCK_AFTER_GAP})"
fi

if tcp_probe 4 1.1.1.1 443 4 >/dev/null 2>&1; then
  fail "ordinary public IPv4 traffic unexpectedly succeeded in the protected gap"
else
  pass "ordinary public IPv4 traffic is unavailable in the protected gap"
fi

printf '\n%s\n' '--- Restore WireGuard under protection ---'

# Prefer an endpoint visible on a logically present interface. Otherwise reuse
# the pre-suspend endpoint.
CURRENT_RAW="$(current_endpoint_raw)"
if [[ -n "$CURRENT_RAW" ]] && parse_endpoint "$CURRENT_RAW"; then
  set_endpoint_values
fi

if add_endpoint; then
  pass "the current PIA endpoint was restored to the allow set"
else
  fail "the PIA endpoint could not be restored"
fi

if endpoint_is_present; then
  pass "the current PIA endpoint is present in the allow set"
else
  fail "the current PIA endpoint is missing from the allow set"
fi

if vpn_is_active; then
  pass "PIA WireGuard began recovering automatically"
else
  if [[ -z "$VPN_UUID" ]]; then
    VPN_UUID="$(
      nmcli -t -f UUID,NAME,TYPE connection show 2>/dev/null \
        | awk -F: '$2 == "PIA Bazzite" && $3 == "wireguard" {
            print $1
            exit
          }'
    )"
  fi

  if [[ -n "$VPN_UUID" ]] \
      && timeout 85s nmcli connection up uuid "$VPN_UUID" \
        >/dev/null 2>&1; then
    pass "NetworkManager reactivated the PIA WireGuard profile"
  else
    fail "NetworkManager could not reactivate the PIA WireGuard profile"
  fi
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake after the controlled gap"
else
  fail "no recent WireGuard handshake appeared after endpoint release"
fi

if tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1; then
  pass "public IPv4 connectivity works again through the VPN"
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
  printf '\nALL SUSPEND AND RESUME TESTS PASSED\n'
  printf 'The independent kill-switch table survived system suspend, protected the\n'
  printf 'network during post-resume recovery, blocked forced physical traffic, and\n'
  printf 'allowed WireGuard to complete a fresh handshake afterward.\n'
  printf 'The temporary table and safety timer were removed.\n'
  exit 0
fi

printf '\nSUSPEND AND RESUME TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'Wi-Fi and PIA were restored where possible.\n'
exit 1
