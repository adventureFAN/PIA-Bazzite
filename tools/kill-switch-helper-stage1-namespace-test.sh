#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$ROOT/helper/pia-bazzite-kill-switch-helper"
REPORT_DIR="$ROOT/test-results/kill-switch/stage1-helper"
REPORT="${1:-$REPORT_DIR/pia-kill-switch-helper-stage1-namespace-test.txt}"
TABLE="pia_bazzite_killswitch_helper_test"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -- "$0" "$@"
  fi
  echo "ERROR: this isolated namespace test needs root privileges." >&2
  exit 1
fi

mkdir -p "$(dirname "$REPORT")"
exec > >(tee "$REPORT") 2>&1

for tool in ip nft ping python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool not found: $tool" >&2
    exit 1
  fi
done

if [[ ! -x "$HELPER" ]]; then
  echo "ERROR: helper launcher is missing or not executable: $HELPER" >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3)"
ID="$$"
SUFFIX="${ID: -5}"
CLIENT_NS="pia-h1-client-$ID"
INET_NS="pia-h1-inet-$ID"
VPN_NS="pia-h1-vpn-$ID"
WAN_A="h1wa$SUFFIX"
WAN_B="h1wb$SUFFIX"
VPN_A="h1va$SUFFIX"
VPN_B="h1vb$SUFFIX"
TMP_DIR="$(mktemp -d /tmp/pia-helper-stage1.XXXXXX)"
FAILURES=0

cleanup() {
  set +e
  ip netns exec "$CLIENT_NS" "$PYTHON_BIN" "$HELPER" emergency-reset \
    >/dev/null 2>&1 || true
  ip netns del "$CLIENT_NS" >/dev/null 2>&1 || true
  ip netns del "$INET_NS" >/dev/null 2>&1 || true
  ip netns del "$VPN_NS" >/dev/null 2>&1 || true
  ip link del "$WAN_A" >/dev/null 2>&1 || true
  ip link del "$VPN_A" >/dev/null 2>&1 || true
  rm -f /run/lock/pia-bazzite-kill-switch-helper-stage1.lock >/dev/null 2>&1 || true
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

helper() {
  ip netns exec "$CLIENT_NS" "$PYTHON_BIN" "$HELPER" "$@"
}

status_field() {
  local field="$1"
  helper status | "$PYTHON_BIN" -c \
    'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$field"
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
    sock.sendto(b"PIA-HELPER-STAGE1", (address, int(port_text)))
    data, _ = sock.recvfrom(1024)
    if data != b"ACK:PIA-HELPER-STAGE1":
        raise SystemExit(2)
PY

udp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"
  ip netns exec "$INET_NS" \
    "$PYTHON_BIN" "$TMP_DIR/udp_server.py" "$family" "$address" "$port" &
  local server_pid=$!
  sleep 0.20
  local result=0
  ip netns exec "$CLIENT_NS" \
    "$PYTHON_BIN" "$TMP_DIR/udp_client.py" "$family" "$address" "$port" \
    >/dev/null 2>&1 || result=$?
  kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" >/dev/null 2>&1 || true
  return "$result"
}

printf 'PIA Bazzite stage-1 restricted helper namespace test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test changes only temporary network namespaces.\n'
printf 'The host firewall, NetworkManager, and real PIA connection are untouched.\n\n'

printf '%s\n' '--- Create isolated network lab ---'
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
ip -n "$CLIENT_NS" link set wan0 up
ip -n "$INET_NS" link set inet0 up
ip -n "$CLIENT_NS" route add default via 198.51.100.1 dev wan0

ip -n "$CLIENT_NS" -6 addr add 2001:db8:10::2/64 dev wan0 nodad
ip -n "$INET_NS" -6 addr add 2001:db8:10::1/64 dev inet0 nodad
ip -n "$INET_NS" -6 addr add 2001:db8:20::1/128 dev inet0 nodad
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
pass "temporary namespaces and veth interfaces were created"
printf '\n'

printf '%s\n' '--- Baseline and strict input validation ---'
expect_success "ordinary IPv4 works before helper protection" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
expect_success "ordinary IPv6 works before helper protection" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
expect_success "simulated VPN IPv4 route works" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
expect_success "simulated VPN IPv6 route works" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1

set +e
INVALID_OUTPUT="$(helper enable --interface 'wan0;id' \
  --endpoint 198.51.100.1:1337 2>&1)"
INVALID_CODE=$?
set -e
if [[ $INVALID_CODE -eq 2 ]] && grep -q '"error": "validation"' <<<"$INVALID_OUTPUT"; then
  pass "unsafe interface input was rejected before nftables execution"
else
  fail "unsafe interface input was not rejected with the validation exit code"
fi

if ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "invalid input unexpectedly created the helper test table"
else
  pass "invalid input did not change the namespace firewall"
fi
printf '\n'

printf '%s\n' '--- Enable and verify the fixed helper table ---'
if helper enable \
    --interface wan0 \
    --endpoint 198.51.100.1:1337 \
    --endpoint '[2001:db8:10::1]:1337'; then
  pass "helper enabled the fixed stage-1 test table"
else
  fail "helper could not enable the fixed stage-1 test table"
fi

if [[ "$(status_field state)" == "active" ]] \
    && [[ "$(status_field verified)" == "True" ]]; then
  pass "status verified the actual nftables table"
else
  fail "status did not verify the active helper table"
fi

expect_blocked "ordinary IPv4 is blocked under helper protection" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
expect_blocked "ordinary IPv6 is blocked under helper protection" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
expect_success "VPN IPv4 remains allowed" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
expect_success "VPN IPv6 remains allowed" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1
expect_success "exact IPv4 WireGuard endpoint remains allowed" \
  udp_probe 4 198.51.100.1 1337
expect_success "exact IPv6 WireGuard endpoint remains allowed" \
  udp_probe 6 2001:db8:10::1 1337
expect_blocked "unlisted UDP destination is blocked" \
  udp_probe 4 203.0.113.1 5353
printf '\n'

printf '%s\n' '--- Idempotent endpoint updates ---'
expect_success "new endpoint can be added" \
  helper add-endpoint --endpoint 198.51.100.1:1444
expect_success "adding the same endpoint again is harmless" \
  helper add-endpoint --endpoint 198.51.100.1:1444
expect_success "newly added endpoint is reachable" \
  udp_probe 4 198.51.100.1 1444
expect_success "endpoint can be removed" \
  helper remove-endpoint --endpoint 198.51.100.1:1444
expect_success "removing the same endpoint again is harmless" \
  helper remove-endpoint --endpoint 198.51.100.1:1444
expect_blocked "removed endpoint is blocked again" \
  udp_probe 4 198.51.100.1 1444
printf '\n'

printf '%s\n' '--- Deliberate disable and cleanup ---'
expect_success "helper disable removes only its fixed test table" helper disable
expect_success "repeated disable is harmless" helper disable
if [[ "$(status_field state)" == "disabled" ]]; then
  pass "status reports disabled after removal"
else
  fail "status does not report disabled after removal"
fi
expect_success "ordinary IPv4 works after helper disable" \
  ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
expect_success "ordinary IPv6 works after helper disable" \
  ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1

if nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "the helper test table was created on the host"
else
  pass "the host has no $TABLE table"
fi
printf '\n'

printf '%s\n' '--- Result ---'
if (( FAILURES == 0 )); then
  printf 'ALL TESTS PASSED\n'
  printf 'The restricted helper generated, applied, verified, updated, and removed\n'
  printf 'only its fixed test table inside an isolated network namespace.\n'
  printf 'Report: %s\n' "$REPORT"
  exit 0
fi

printf '%d TEST(S) FAILED\n' "$FAILURES"
printf 'The helper must not advance to polkit integration yet.\n'
printf 'Report: %s\n' "$REPORT"
exit 1
