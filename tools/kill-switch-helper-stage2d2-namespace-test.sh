#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
TARGET="/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper"
TABLE="pia_bazzite_killswitch_helper_test"
LOCK="/run/lock/pia-bazzite-kill-switch-helper.lock"
BRIDGE_SOURCE="$ROOT/tools/pia-bazzite-stage2-netns-polkit-bridge.py"
BRIDGE_TARGET="/usr/local/libexec/pia-bazzite/pia-bazzite-stage2-netns-test-bridge"
REPORT_DIR="$ROOT/test-results/kill-switch/stage2-polkit"
REPORT="$REPORT_DIR/pia-kill-switch-helper-stage2d2-namespace-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  echo "ERROR: run this test as your normal desktop user, not as root." >&2
  exit 1
fi

for tool in sudo ip nft ping pkexec python3; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "ERROR: required tool not found: $tool" >&2
    exit 1
  }
done

USER_ID="$(id -u)"
PKEXEC="$(command -v pkexec)"
PYTHON="$(command -v python3)"
ID="$$"
SUFFIX="${ID: -5}"
CLIENT_NS="pia-h2-client-$ID"
INET_NS="pia-h2-inet-$ID"
VPN_NS="pia-h2-vpn-$ID"
WAN_A="d2wa$SUFFIX"
WAN_B="d2wb$SUFFIX"
LAN_A="d2la$SUFFIX"
LAN_B="d2lb$SUFFIX"
VPN_A="d2va$SUFFIX"
VPN_B="d2vb$SUFFIX"
TMP_DIR="$(mktemp -d /tmp/pia-helper-stage2d2.XXXXXX)"
INSTALLED=0
BRIDGE_INSTALLED=0
NAMESPACES=0
PASS=0
FAIL=0

OLD4="198.51.100.10"
NEW4="198.51.100.11"
ORD4="198.51.100.200"
OLD6="2001:db8:100::10"
NEW6="2001:db8:100::11"
ORD6="2001:db8:100::200"

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }

cleanup() {
  set +e
  if [[ $NAMESPACES -eq 1 ]]; then
    sudo -n ip netns exec "$CLIENT_NS" nft destroy table inet "$TABLE" >/dev/null 2>&1 || true
    sudo -n ip netns del "$CLIENT_NS" >/dev/null 2>&1 || true
    sudo -n ip netns del "$INET_NS" >/dev/null 2>&1 || true
    sudo -n ip netns del "$VPN_NS" >/dev/null 2>&1 || true
    sudo -n ip link del "$WAN_A" >/dev/null 2>&1 || true
    sudo -n ip link del "$LAN_A" >/dev/null 2>&1 || true
    sudo -n ip link del "$VPN_A" >/dev/null 2>&1 || true
  fi
  sudo -n rm -f -- "$LOCK" >/dev/null 2>&1 || true
  if [[ $BRIDGE_INSTALLED -eq 1 ]]; then
    if [[ -f "$BRIDGE_TARGET" && ! -L "$BRIDGE_TARGET" ]] \
        && [[ "$(stat -c '%u:%g' -- "$BRIDGE_TARGET" 2>/dev/null)" == "0:0" ]]; then
      sudo -n rm -f -- "$BRIDGE_TARGET" >/dev/null 2>&1 || true
    fi
  fi
  if [[ $INSTALLED -eq 1 ]]; then
    sudo -n "$INSTALLER" uninstall >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT INT TERM HUP

expect_success() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi
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

bridge_pkexec() {
  local operation="$1"
  "$PKEXEC" --disable-internal-agent "$BRIDGE_TARGET" "$CLIENT_NS" "$operation"
}

bridge_root_harness() {
  local operation="$1"
  sudo -n /usr/bin/env PKEXEC_UID="$USER_ID" \
    "$BRIDGE_TARGET" "$CLIENT_NS" "$operation"
}

validate_json() {
  local expected_action="$1"
  "$PYTHON" -c '
import json, sys
expected=sys.argv[1]
p=json.load(sys.stdin)
assert p["ok"] is True
assert p["action"] == expected
assert p["verified"] is True
assert p["table"] == "pia_bazzite_killswitch_helper_test"
assert p["table_generation"] == 1
assert "set-interfaces" in p["capabilities"]
assert "set-endpoints" in p["capabilities"]
' "$expected_action"
}

cat > "$TMP_DIR/udp_server.py" <<'PY'
from __future__ import annotations
import socket, sys
family_name, address, port_text = sys.argv[1:4]
family = socket.AF_INET6 if family_name == "6" else socket.AF_INET
with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.bind((address, int(port_text)))
    sock.settimeout(2.0)
    try:
        data, peer = sock.recvfrom(1024)
    except TimeoutError:
        raise SystemExit(3)
    sock.sendto(b"ACK:" + data, peer)
PY

cat > "$TMP_DIR/udp_client.py" <<'PY'
from __future__ import annotations
import socket, sys
family_name, address, port_text = sys.argv[1:4]
family = socket.AF_INET6 if family_name == "6" else socket.AF_INET
with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.settimeout(1.2)
    sock.sendto(b"PIA-STAGE2D2", (address, int(port_text)))
    data, _ = sock.recvfrom(1024)
    if data != b"ACK:PIA-STAGE2D2":
        raise SystemExit(2)
PY

udp_probe() {
  local family="$1" address="$2" port="$3"
  sudo -n ip netns exec "$INET_NS" \
    "$PYTHON" "$TMP_DIR/udp_server.py" "$family" "$address" "$port" &
  local server_pid=$!
  sleep 0.20
  local result=0
  sudo -n ip netns exec "$CLIENT_NS" \
    "$PYTHON" "$TMP_DIR/udp_client.py" "$family" "$address" "$port" \
    >/dev/null 2>&1 || result=$?
  sudo -n kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" >/dev/null 2>&1 || true
  return "$result"
}

printf 'PIA Bazzite stage-2D.2 production-structure namespace test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test installs the restricted helper and applies the production-like\n'
printf 'set-based nftables structure only inside temporary network namespaces.\n'
printf 'The host firewall, NetworkManager, and PIA profile are not changed.\n\n'

printf '%s\n' '--- One-time authorization and installation preconditions ---'
# Cache sudo once. Every later cleanup command uses sudo -n, so cancellation
# cannot create a repeated terminal-password loop.
sudo -v
if pgrep -u "$USER_ID" -f 'polkit.*agent|polkit-kde' >/dev/null 2>&1; then
  pass "graphical Polkit authentication agent is running"
else
  fail "no graphical Polkit authentication agent detected"
fi
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "candidate helper table already exists on the host"
else
  pass "host does not contain the candidate helper table"
fi
if sudo -n "$INSTALLER" install; then
  INSTALLED=1
  pass "restricted helper installed under the fixed root-owned path"
else
  fail "restricted helper installation failed"
fi
if [[ -e "$BRIDGE_TARGET" || -L "$BRIDGE_TARGET" ]]; then
  fail "fixed namespace bridge path already exists"
elif sudo -n /usr/bin/install -o root -g root -m 0755 -- "$BRIDGE_SOURCE" "$BRIDGE_TARGET"; then
  BRIDGE_INSTALLED=1
  pass "fixed root-owned namespace bridge installed"
else
  fail "namespace bridge installation failed"
fi
printf '\n'

if [[ $FAIL -eq 0 ]]; then
  printf '%s\n' '--- Create two-uplink isolated network lab ---'
  sudo -n ip netns add "$CLIENT_NS"
  sudo -n ip netns add "$INET_NS"
  sudo -n ip netns add "$VPN_NS"
  NAMESPACES=1

  sudo -n ip link add "$WAN_A" type veth peer name "$WAN_B"
  sudo -n ip link set "$WAN_A" netns "$CLIENT_NS"
  sudo -n ip link set "$WAN_B" netns "$INET_NS"
  sudo -n ip -n "$CLIENT_NS" link set "$WAN_A" name wan0
  sudo -n ip -n "$INET_NS" link set "$WAN_B" name inet-wan0

  sudo -n ip link add "$LAN_A" type veth peer name "$LAN_B"
  sudo -n ip link set "$LAN_A" netns "$CLIENT_NS"
  sudo -n ip link set "$LAN_B" netns "$INET_NS"
  sudo -n ip -n "$CLIENT_NS" link set "$LAN_A" name lan0
  sudo -n ip -n "$INET_NS" link set "$LAN_B" name inet-lan0

  sudo -n ip link add "$VPN_A" type veth peer name "$VPN_B"
  sudo -n ip link set "$VPN_A" netns "$CLIENT_NS"
  sudo -n ip link set "$VPN_B" netns "$VPN_NS"
  sudo -n ip -n "$CLIENT_NS" link set "$VPN_A" name piabazzite
  sudo -n ip -n "$VPN_NS" link set "$VPN_B" name vpn0

  for namespace in "$CLIENT_NS" "$INET_NS" "$VPN_NS"; do
    sudo -n ip -n "$namespace" link set lo up
  done

  sudo -n ip -n "$CLIENT_NS" addr add 192.0.2.2/24 dev wan0
  sudo -n ip -n "$INET_NS" addr add 192.0.2.1/24 dev inet-wan0
  sudo -n ip -n "$CLIENT_NS" addr add 192.0.3.2/24 dev lan0
  sudo -n ip -n "$INET_NS" addr add 192.0.3.1/24 dev inet-lan0
  sudo -n ip -n "$CLIENT_NS" -6 addr add 2001:db8:10::2/64 dev wan0 nodad
  sudo -n ip -n "$INET_NS" -6 addr add 2001:db8:10::1/64 dev inet-wan0 nodad
  sudo -n ip -n "$CLIENT_NS" -6 addr add 2001:db8:11::2/64 dev lan0 nodad
  sudo -n ip -n "$INET_NS" -6 addr add 2001:db8:11::1/64 dev inet-lan0 nodad
  for device in wan0 lan0; do sudo -n ip -n "$CLIENT_NS" link set "$device" up; done
  for device in inet-wan0 inet-lan0; do sudo -n ip -n "$INET_NS" link set "$device" up; done

  for address in "$OLD4" "$NEW4" "$ORD4"; do
    sudo -n ip -n "$INET_NS" addr add "$address/32" dev lo
    sudo -n ip -n "$CLIENT_NS" route add "$address/32" via 192.0.2.1 dev wan0
  done
  for address in "$OLD6" "$NEW6" "$ORD6"; do
    sudo -n ip -n "$INET_NS" -6 addr add "$address/128" dev lo nodad
    sudo -n ip -n "$CLIENT_NS" -6 route add "$address/128" via 2001:db8:10::1 dev wan0
  done

  sudo -n ip -n "$CLIENT_NS" addr add 10.77.0.2/24 dev piabazzite
  sudo -n ip -n "$VPN_NS" addr add 10.77.0.1/24 dev vpn0
  sudo -n ip -n "$VPN_NS" addr add 192.0.4.1/32 dev lo
  sudo -n ip -n "$CLIENT_NS" -6 addr add fd42:5049:4200::2/64 dev piabazzite nodad
  sudo -n ip -n "$VPN_NS" -6 addr add fd42:5049:4200::1/64 dev vpn0 nodad
  sudo -n ip -n "$VPN_NS" -6 addr add 2001:db8:300::1/128 dev lo nodad
  sudo -n ip -n "$CLIENT_NS" link set piabazzite up
  sudo -n ip -n "$VPN_NS" link set vpn0 up
  sudo -n ip -n "$CLIENT_NS" route add 192.0.4.1/32 via 10.77.0.1 dev piabazzite
  sudo -n ip -n "$CLIENT_NS" -6 route add 2001:db8:300::1/128 \
    via fd42:5049:4200::1 dev piabazzite
  pass "temporary namespaces, two physical uplinks, and simulated VPN were created"
  printf '\n'

  printf '%s\n' '--- Baseline traffic ---'
  expect_success "ordinary IPv4 works before protection" \
    sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
  expect_success "ordinary IPv6 works before protection" \
    sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 "$ORD6"
  expect_success "old IPv4 endpoint is reachable before protection" udp_probe 4 "$OLD4" 1337
  expect_success "old IPv6 endpoint is reachable before protection" udp_probe 6 "$OLD6" 1337
  expect_success "simulated VPN IPv4 route works" \
    sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.4.1
  expect_success "simulated VPN IPv6 route works" \
    sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:300::1
  printf '\n'

  printf '%s\n' '--- Graphical Polkit enable using the installed helper ---'
  echo "A graphical Polkit password dialog should appear now."
  set +e
  enable_output="$(bridge_pkexec enable 2>&1)"
  enable_code=$?
  set -e
  printf '%s\n' "$enable_output"
  if [[ $enable_code -eq 0 ]]; then
    pass "desktop-session Polkit authorized the fixed bridge and helper"
  else
    fail "Polkit/bridge/helper enable returned exit code $enable_code"
  fi
  if validate_json enable <<<"$enable_output"; then
    pass "enable response verifies the production-like table structure"
  else
    fail "enable JSON verification failed"
  fi
  if sudo -n ip netns exec "$CLIENT_NS" nft list set inet "$TABLE" physical_interfaces \
      | grep -q 'wan0'; then
    pass "physical-interface set contains wan0"
  else
    fail "physical-interface set does not contain wan0"
  fi
  if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
    fail "candidate table was created on the host"
  else
    pass "candidate table exists only inside the client namespace"
  fi
  printf '\n'

  printf '%s\n' '--- Protection with initial interface and endpoint sets ---'
  expect_blocked "ordinary IPv4 is blocked" \
    sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
  expect_blocked "ordinary IPv6 is blocked" \
    sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 "$ORD6"
  expect_success "exact old IPv4 endpoint remains allowed" udp_probe 4 "$OLD4" 1337
  expect_success "exact old IPv6 endpoint remains allowed" udp_probe 6 "$OLD6" 1337
  expect_blocked "wrong UDP port is blocked" udp_probe 4 "$OLD4" 1555
  expect_success "simulated VPN IPv4 remains allowed" \
    sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.4.1
  expect_success "simulated VPN IPv6 remains allowed" \
    sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:300::1
  printf '\n'

  printf '%s\n' '--- Atomic endpoint-set replacement ---'
  set_output="$(bridge_root_harness set-endpoints 2>&1)" || true
  printf '%s\n' "$set_output"
  if validate_json set-endpoints <<<"$set_output"; then
    pass "both endpoint families were replaced in one helper transaction"
  else
    fail "set-endpoints JSON verification failed"
  fi
  expect_success "new IPv4 endpoint is allowed after replacement" udp_probe 4 "$NEW4" 1443
  expect_success "new IPv6 endpoint is allowed after replacement" udp_probe 6 "$NEW6" 1443
  expect_blocked "retired old IPv4 endpoint is blocked" udp_probe 4 "$OLD4" 1337
  expect_blocked "retired old IPv6 endpoint is blocked" udp_probe 6 "$OLD6" 1337
  printf '\n'

  printf '%s\n' '--- Atomic physical-interface replacement ---'
  interface_output="$(bridge_root_harness set-interfaces 2>&1)" || true
  printf '%s\n' "$interface_output"
  if validate_json set-interfaces <<<"$interface_output"; then
    pass "physical-interface set was replaced in one helper transaction"
  else
    fail "set-interfaces JSON verification failed"
  fi
  expect_blocked "new endpoint is blocked while its route still uses retired wan0" \
    udp_probe 4 "$NEW4" 1443

  for address in "$OLD4" "$NEW4" "$ORD4"; do
    sudo -n ip -n "$CLIENT_NS" route replace "$address/32" via 192.0.3.1 dev lan0
  done
  for address in "$OLD6" "$NEW6" "$ORD6"; do
    sudo -n ip -n "$CLIENT_NS" -6 route replace "$address/128" via 2001:db8:11::1 dev lan0
  done
  expect_success "new IPv4 endpoint is allowed through lan0" udp_probe 4 "$NEW4" 1443
  expect_success "new IPv6 endpoint is allowed through lan0" udp_probe 6 "$NEW6" 1443
  expect_blocked "ordinary IPv4 remains blocked after interface switch" \
    sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
  printf '\n'

  printf '%s\n' '--- Incremental endpoint add and remove ---'
  add_output="$(bridge_root_harness add-endpoint 2>&1)" || true
  if validate_json add-endpoint <<<"$add_output"; then
    pass "old IPv4 endpoint was added without rebuilding the table"
  else
    fail "add-endpoint JSON verification failed"
  fi
  expect_success "added old IPv4 endpoint is reachable through lan0" udp_probe 4 "$OLD4" 1337
  remove_output="$(bridge_root_harness remove-endpoint 2>&1)" || true
  if validate_json remove-endpoint <<<"$remove_output"; then
    pass "old IPv4 endpoint was removed without rebuilding the table"
  else
    fail "remove-endpoint JSON verification failed"
  fi
  expect_blocked "removed old IPv4 endpoint is blocked again" udp_probe 4 "$OLD4" 1337
  printf '\n'

  printf '%s\n' '--- Deliberate disable ---'
  disable_output="$(bridge_root_harness disable 2>&1)" || true
  printf '%s\n' "$disable_output"
  if "$PYTHON" -c '
import json,sys
p=json.load(sys.stdin)
assert p["ok"] is True
assert p["action"] == "disable"
assert p["state"] == "disabled"
assert p["present"] is False
assert p["verified"] is True
' <<<"$disable_output"; then
    pass "disable removed only the fixed candidate table"
  else
    fail "disable JSON verification failed"
  fi
  expect_success "ordinary IPv4 works again after disable" \
    sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
  expect_success "ordinary IPv6 works again after disable" \
    sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 "$ORD6"
  if sudo -n ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" >/dev/null 2>&1; then
    fail "candidate table remains inside the client namespace"
  else
    pass "candidate table is absent after deliberate disable"
  fi
fi

printf '\n%s\n' '--- Explicit root-owned test installation cleanup ---'
if [[ $BRIDGE_INSTALLED -eq 1 ]]; then
  if sudo -n rm -f -- "$BRIDGE_TARGET"; then
    BRIDGE_INSTALLED=0
    pass "root-owned namespace bridge was removed"
  else
    fail "root-owned namespace bridge could not be removed"
  fi
fi
if [[ $INSTALLED -eq 1 ]]; then
  if sudo -n "$INSTALLER" uninstall; then
    INSTALLED=0
    pass "root-owned helper installation was removed"
  else
    fail "root-owned helper installation could not be removed"
  fi
fi
sudo -n rm -f -- "$LOCK" >/dev/null 2>&1 || true

printf '\n%s\n' '--- Result ---'
printf 'PASS: %d\n' "$PASS"
printf 'FAIL: %d\n' "$FAIL"
if [[ $FAIL -eq 0 ]]; then
  printf 'ALL STAGE-2D.2 PRODUCTION-STRUCTURE TESTS PASSED\n'
  printf 'Report: %s\n' "$REPORT"
  exit 0
fi
printf 'STAGE-2D.2 PRODUCTION-STRUCTURE TEST FAILED\n'
printf 'Report: %s\n' "$REPORT"
exit 1
