#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -- "$0" "$@"
  fi
  echo "ERROR: this isolated namespace test needs root privileges." >&2
  exit 1
fi

for tool in ip nft ping python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool not found: $tool" >&2
    exit 1
  fi
done

ID="$$"
CLIENT_NS="pia-ks-client-$ID"
INET_NS="pia-ks-inet-$ID"
VPN_NS="pia-ks-vpn-$ID"
WAN_A="kswa${ID: -5}"
WAN_B="kswb${ID: -5}"
VPN_A="ksva${ID: -5}"
VPN_B="ksvb${ID: -5}"
TABLE="pia_bazzite_killswitch"
TMP_DIR="$(mktemp -d /tmp/pia-ks-lab.XXXXXX)"
FAILURES=0

cleanup() {
  set +e
  ip netns del "$CLIENT_NS" >/dev/null 2>&1
  ip netns del "$INET_NS" >/dev/null 2>&1
  ip netns del "$VPN_NS" >/dev/null 2>&1
  ip link del "$WAN_A" >/dev/null 2>&1
  ip link del "$VPN_A" >/dev/null 2>&1
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

pass() {
  printf 'PASS  %s\n' "$1"
}

fail() {
  printf 'FAIL  %s\n' "$1"
  FAILURES=$((FAILURES + 1))
}

expect_success() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    pass "$name"
  else
    fail "$name"
  fi
}

expect_blocked() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    fail "$name (traffic unexpectedly succeeded)"
  else
    pass "$name"
  fi
}

cat > "$TMP_DIR/udp_server.py" <<'PY'
from __future__ import annotations

import socket
import sys

family_name, address, port_text = sys.argv[1:4]
family = socket.AF_INET6 if family_name == "6" else socket.AF_INET
with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((address, int(port_text)))
    data, peer = sock.recvfrom(1024)
    sock.sendto(b"ACK:" + data, peer)
PY

cat > "$TMP_DIR/udp_client.py" <<'PY'
from __future__ import annotations

import socket
import sys

family_name, address, port_text = sys.argv[1:4]
family = socket.AF_INET6 if family_name == "6" else socket.AF_INET
with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.settimeout(1.5)
    sock.sendto(b"PIA-KS-TEST", (address, int(port_text)))
    data, _ = sock.recvfrom(1024)
    if data != b"ACK:PIA-KS-TEST":
        raise SystemExit(2)
PY

udp_allowed() {
  local family="$1"
  local address="$2"
  local port="$3"
  ip netns exec "$INET_NS" \
    python3 "$TMP_DIR/udp_server.py" "$family" "$address" "$port" &
  local server_pid=$!
  sleep 0.20
  local result=0
  ip netns exec "$CLIENT_NS" \
    python3 "$TMP_DIR/udp_client.py" "$family" "$address" "$port" \
    >/dev/null 2>&1 || result=$?
  wait "$server_pid" >/dev/null 2>&1 || true
  return "$result"
}

udp_blocked() {
  local family="$1"
  local address="$2"
  local port="$3"
  ip netns exec "$INET_NS" \
    python3 "$TMP_DIR/udp_server.py" "$family" "$address" "$port" &
  local server_pid=$!
  sleep 0.20
  local result=0
  ip netns exec "$CLIENT_NS" \
    python3 "$TMP_DIR/udp_client.py" "$family" "$address" "$port" \
    >/dev/null 2>&1 || result=$?
  kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" >/dev/null 2>&1 || true
  [[ $result -ne 0 ]]
}

printf 'PIA Bazzite isolated session kill-switch test\n'
printf 'This creates three temporary network namespaces.\n'
printf 'It does not change the host firewall or use the real internet connection.\n\n'

# Create isolated client, ordinary-internet, and VPN namespaces.
ip netns add "$CLIENT_NS"
ip netns add "$INET_NS"
ip netns add "$VPN_NS"

ip link add "$WAN_A" type veth peer name "$WAN_B"
ip link set "$WAN_A" netns "$CLIENT_NS"
ip link set "$WAN_B" netns "$INET_NS"
ip -n "$CLIENT_NS" link set "$WAN_A" name wan0
ip -n "$INET_NS" link set "$WAN_B" name inet0

ip link add "$VPN_A" type veth peer name "$VPN_B"
ip link set "$VPN_A" netns "$CLIENT_NS"
ip link set "$VPN_B" netns "$VPN_NS"
ip -n "$CLIENT_NS" link set "$VPN_A" name piabazzite
ip -n "$VPN_NS" link set "$VPN_B" name vpn0

for namespace in "$CLIENT_NS" "$INET_NS" "$VPN_NS"; do
  ip -n "$namespace" link set lo up
done

ip -n "$CLIENT_NS" addr add 198.51.100.2/24 dev wan0
ip -n "$INET_NS" addr add 198.51.100.1/24 dev inet0
ip -n "$INET_NS" addr add 203.0.113.1/32 dev inet0
ip -n "$INET_NS" addr add 192.0.2.1/32 dev inet0
ip -n "$CLIENT_NS" link set wan0 up
ip -n "$INET_NS" link set inet0 up
ip -n "$CLIENT_NS" route add default via 198.51.100.1 dev wan0

ip -n "$CLIENT_NS" -6 addr add 2001:db8:10::2/64 dev wan0 nodad
ip -n "$INET_NS" -6 addr add 2001:db8:10::1/64 dev inet0 nodad
ip -n "$INET_NS" -6 addr add 2001:db8:20::1/128 dev inet0 nodad
ip -n "$INET_NS" -6 addr add 2001:db8:30::1/128 dev inet0 nodad
ip -n "$CLIENT_NS" -6 route add default via 2001:db8:10::1 dev wan0

ip -n "$CLIENT_NS" addr add 10.77.0.2/24 dev piabazzite
ip -n "$VPN_NS" addr add 10.77.0.1/24 dev vpn0
ip -n "$VPN_NS" addr add 192.0.2.1/32 dev vpn0
ip -n "$CLIENT_NS" link set piabazzite up
ip -n "$VPN_NS" link set vpn0 up
ip -n "$CLIENT_NS" route add 192.0.2.1/32 via 10.77.0.1 dev piabazzite

ip -n "$CLIENT_NS" -6 addr add fd42:5049:4100::2/64 dev piabazzite nodad
ip -n "$VPN_NS" -6 addr add fd42:5049:4100::1/64 dev vpn0 nodad
ip -n "$VPN_NS" -6 addr add 2001:db8:30::1/128 dev vpn0 nodad
ip -n "$CLIENT_NS" -6 route add 2001:db8:30::1/128 \
  via fd42:5049:4100::1 dev piabazzite

printf '%s\n' '--- Baseline without a kill switch ---'
expect_success "ordinary IPv4 traffic works before protection" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
expect_success "ordinary IPv6 traffic works before protection" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
expect_success "simulated VPN IPv4 route works" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
expect_success "simulated VPN IPv6 route works" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1
expect_success "simulated WireGuard endpoint is reachable over UDP/IPv4" \
  udp_allowed 4 198.51.100.1 1337
expect_success "simulated WireGuard endpoint is reachable over UDP/IPv6" \
  udp_allowed 6 2001:db8:10::1 1337
printf '\n'

# The prospective session kill switch. Only the isolated client namespace is
# modified. The host nftables ruleset remains untouched.
ip netns exec "$CLIENT_NS" nft -f - <<NFT
add table inet $TABLE
add chain inet $TABLE output { type filter hook output priority -100; policy accept; }
add rule inet $TABLE output oifname "lo" counter accept comment "loopback"
add rule inet $TABLE output ip daddr 198.51.100.1 udp dport 1337 counter accept comment "WireGuard endpoint IPv4"
add rule inet $TABLE output ip6 daddr 2001:db8:10::1 udp dport 1337 counter accept comment "WireGuard endpoint IPv6"
add rule inet $TABLE output oifname "piabazzite" counter accept comment "VPN tunnel"
add rule inet $TABLE output counter reject with icmpx type admin-prohibited comment "block outside VPN"
NFT

printf '%s\n' '--- Protection active ---'
expect_blocked "ordinary IPv4 traffic is blocked" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
expect_blocked "ordinary IPv6 traffic is blocked" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
expect_success "VPN IPv4 traffic remains allowed" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
expect_success "VPN IPv6 traffic remains allowed" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1
expect_success "WireGuard endpoint UDP/IPv4 remains allowed" \
  udp_allowed 4 198.51.100.1 1337
expect_success "WireGuard endpoint UDP/IPv6 remains allowed" \
  udp_allowed 6 2001:db8:10::1 1337
expect_success "DNS-like UDP outside the VPN is blocked" \
  udp_blocked 4 203.0.113.1 5353
printf '\n'

printf '%s\n' '--- Simulated tunnel failure ---'
ip -n "$CLIENT_NS" link del piabazzite
expect_blocked "IPv4 cannot fall back to the ordinary connection" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
expect_blocked "IPv6 cannot fall back to the ordinary connection" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1
expect_success "WireGuard endpoint is still reachable for reconnection" \
  udp_allowed 4 198.51.100.1 1337
printf '\n'

printf '%s\n' '--- nftables counters inside the isolated client ---'
ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" || true
printf '\n'

printf '%s\n' '--- Deliberate reset ---'
ip netns exec "$CLIENT_NS" nft delete table inet "$TABLE"
expect_success "ordinary IPv4 traffic works after reset" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
expect_success "ordinary IPv6 traffic works after reset" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
expect_success "former VPN destination can use the ordinary route after reset" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
printf '\n'

if nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "the test accidentally created a kill-switch table on the host"
else
  pass "the host has no $TABLE table"
fi

printf '\n'
printf '%s\n' '--- Result ---'
if (( FAILURES == 0 )); then
  printf 'ALL TESTS PASSED\n'
  printf 'The basic nftables rule model behaves correctly in isolation.\n'
  printf 'No real PIA connection or host firewall was modified.\n'
  exit 0
fi

printf '%d TEST(S) FAILED\n' "$FAILURES"
printf 'The prototype must not be used on the real host yet.\n'
exit 1
