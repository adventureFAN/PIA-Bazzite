#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
BRIDGE_SOURCE="$ROOT/tools/pia-bazzite-stage3-client-netns-bridge.py"
DRIVER="$ROOT/tools/pia-bazzite-stage3-client-driver.py"
PROBE_SOURCE="$ROOT/tools/pia-bazzite-stage3-client-probe.py"
SHIM_SOURCE="$ROOT/tools/pia-bazzite-stage3-client-process-shim.py"
TARGET_DIR="/usr/local/libexec/pia-bazzite"
TOKEN="$$"
CLIENT_NS="pia-h3-client-$TOKEN"
INET_NS="pia-h3-inet-$TOKEN"
VPN_NS="pia-h3-vpn-$TOKEN"
BRIDGE_TARGET="$TARGET_DIR/pia-bazzite-stage3-client-netns-bridge-$TOKEN"
INVALID_PROBE="$TARGET_DIR/pia-bazzite-stage3-invalid-response-probe"
TIMEOUT_PROBE="$TARGET_DIR/pia-bazzite-stage3-timeout-probe"
PROCESS_SHIM="$TARGET_DIR/pia-bazzite-stage3-process-shim"
TABLE="pia_bazzite_killswitch_helper_test"
REPORT_DIR="$ROOT/test-results/kill-switch/stage3-client"
REPORT="$REPORT_DIR/pia-kill-switch-client-stage3b-namespace-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

PASS=0
FAIL=0
INSTALLED=0
BRIDGE_INSTALLED=0
PROBES_INSTALLED=0
SHIM_INSTALLED=0
NAMESPACES=0

OLD4="198.51.100.10"
NEW4="198.51.100.11"
ORD4="198.51.100.99"
OLD6="2001:db8:100::10"
NEW6="2001:db8:100::11"
ORD6="2001:db8:100::99"

pass() { printf 'PASS  %s\n' "$*"; PASS=$((PASS + 1)); }
fail() { printf 'FAIL  %s\n' "$*"; FAIL=$((FAIL + 1)); }

cleanup() {
  set +e
  if [[ $NAMESPACES -eq 1 ]]; then
    sudo -n ip netns exec "$CLIENT_NS" nft destroy table inet "$TABLE" >/dev/null 2>&1 || true
    sudo -n ip netns del "$CLIENT_NS" >/dev/null 2>&1 || true
    sudo -n ip netns del "$INET_NS" >/dev/null 2>&1 || true
    sudo -n ip netns del "$VPN_NS" >/dev/null 2>&1 || true
  fi
  if [[ $BRIDGE_INSTALLED -eq 1 ]]; then
    sudo -n rm -f -- "$BRIDGE_TARGET" >/dev/null 2>&1 || true
  fi
  if [[ $PROBES_INSTALLED -eq 1 ]]; then
    sudo -n rm -f -- "$INVALID_PROBE" "$TIMEOUT_PROBE" >/dev/null 2>&1 || true
  fi
  if [[ $SHIM_INSTALLED -eq 1 ]]; then
    sudo -n rm -f -- "$PROCESS_SHIM" >/dev/null 2>&1 || true
  fi
  if [[ $INSTALLED -eq 1 ]]; then
    sudo -n "$INSTALLER" uninstall >/dev/null 2>&1 || true
  fi
  sudo -n rm -f /run/lock/pia-bazzite-kill-switch-helper-stage1.lock >/dev/null 2>&1 || true
}
trap cleanup EXIT

client_call() {
  local operation="$1"
  python3 -I "$DRIVER" "$BRIDGE_TARGET" "$operation"
}

validate_client_status() {
  local action="$1" state="$2" active="$3"
  python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p["client_ok"] is True
assert p["action"] == sys.argv[1]
assert p["state"] == sys.argv[2]
assert p["verified"] is True
assert p["protection_active"] is (sys.argv[3] == "true")
' "$action" "$state" "$active"
}

expect_success() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi
}
expect_blocked() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then fail "$label"; else pass "$label"; fi
}

printf 'PIA Bazzite stage-3B real-client Polkit namespace test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'The real Python client drives the installed helper through graphical Polkit.\n'
printf 'All nftables changes are confined to temporary network namespaces.\n\n'

printf '%s\n' '--- One-time installation and laboratory setup ---'
sudo -v
for command in pkexec pkcheck nft ip python3 timeout install pgrep; do
  command -v "$command" >/dev/null 2>&1 || { fail "required command missing: $command"; exit 1; }
done
if pgrep -u "$(id -u)" -f 'polkit.*agent|polkit-kde' >/dev/null 2>&1; then
  pass "graphical Polkit authentication agent is running"
else
  fail "no graphical Polkit authentication agent detected"
fi
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "host already contains the helper test table"
else
  pass "host does not contain the helper test table"
fi
if sudo -n "$INSTALLER" install; then INSTALLED=1; pass "restricted helper installed"; else fail "helper installation failed"; fi
if [[ -e "$BRIDGE_TARGET" || -L "$BRIDGE_TARGET" ]]; then
  fail "tokenized bridge path already exists"
elif sudo -n install -o root -g root -m 0755 -- "$BRIDGE_SOURCE" "$BRIDGE_TARGET"; then
  BRIDGE_INSTALLED=1; pass "tokenized root-owned client bridge installed"
else
  fail "client bridge installation failed"
fi
if [[ -e "$INVALID_PROBE" || -L "$INVALID_PROBE" || -e "$TIMEOUT_PROBE" || -L "$TIMEOUT_PROBE" ]]; then
  fail "fixed client probe path already exists"
elif sudo -n install -o root -g root -m 0755 -- "$PROBE_SOURCE" "$INVALID_PROBE" \
  && sudo -n install -o root -g root -m 0755 -- "$PROBE_SOURCE" "$TIMEOUT_PROBE"; then
  PROBES_INSTALLED=1; pass "root-owned invalid-response and timeout probes installed"
else
  fail "client probe installation failed"
fi
if [[ -e "$PROCESS_SHIM" || -L "$PROCESS_SHIM" ]]; then
  fail "fixed process-shim path already exists"
elif sudo -n install -o root -g root -m 0755 -- "$SHIM_SOURCE" "$PROCESS_SHIM"; then
  SHIM_INSTALLED=1; pass "root-owned deterministic process shim installed"
else
  fail "process shim installation failed"
fi

sudo -n ip netns add "$CLIENT_NS"
sudo -n ip netns add "$INET_NS"
sudo -n ip netns add "$VPN_NS"
NAMESPACES=1
sudo -n ip link add "h3wA$TOKEN" type veth peer name "h3wB$TOKEN"
sudo -n ip link set "h3wA$TOKEN" netns "$CLIENT_NS"
sudo -n ip link set "h3wB$TOKEN" netns "$INET_NS"
sudo -n ip -n "$CLIENT_NS" link set "h3wA$TOKEN" name wan0
sudo -n ip -n "$INET_NS" link set "h3wB$TOKEN" name inet-wan0
sudo -n ip link add "h3lA$TOKEN" type veth peer name "h3lB$TOKEN"
sudo -n ip link set "h3lA$TOKEN" netns "$CLIENT_NS"
sudo -n ip link set "h3lB$TOKEN" netns "$INET_NS"
sudo -n ip -n "$CLIENT_NS" link set "h3lA$TOKEN" name lan0
sudo -n ip -n "$INET_NS" link set "h3lB$TOKEN" name inet-lan0
sudo -n ip link add "h3vA$TOKEN" type veth peer name "h3vB$TOKEN"
sudo -n ip link set "h3vA$TOKEN" netns "$CLIENT_NS"
sudo -n ip link set "h3vB$TOKEN" netns "$VPN_NS"
sudo -n ip -n "$CLIENT_NS" link set "h3vA$TOKEN" name piabazzite
sudo -n ip -n "$VPN_NS" link set "h3vB$TOKEN" name vpn0
for ns in "$CLIENT_NS" "$INET_NS" "$VPN_NS"; do sudo -n ip -n "$ns" link set lo up; done
sudo -n ip -n "$CLIENT_NS" addr add 192.0.2.2/24 dev wan0
sudo -n ip -n "$INET_NS" addr add 192.0.2.1/24 dev inet-wan0
sudo -n ip -n "$CLIENT_NS" addr add 192.0.3.2/24 dev lan0
sudo -n ip -n "$INET_NS" addr add 192.0.3.1/24 dev inet-lan0
sudo -n ip -n "$CLIENT_NS" -6 addr add 2001:db8:10::2/64 dev wan0 nodad
sudo -n ip -n "$INET_NS" -6 addr add 2001:db8:10::1/64 dev inet-wan0 nodad
sudo -n ip -n "$CLIENT_NS" -6 addr add 2001:db8:11::2/64 dev lan0 nodad
sudo -n ip -n "$INET_NS" -6 addr add 2001:db8:11::1/64 dev inet-lan0 nodad
for dev in wan0 lan0; do sudo -n ip -n "$CLIENT_NS" link set "$dev" up; done
for dev in inet-wan0 inet-lan0; do sudo -n ip -n "$INET_NS" link set "$dev" up; done
for addr in "$OLD4" "$NEW4" "$ORD4"; do
  sudo -n ip -n "$INET_NS" addr add "$addr/32" dev lo
  sudo -n ip -n "$CLIENT_NS" route add "$addr/32" via 192.0.2.1 dev wan0
done
for addr in "$OLD6" "$NEW6" "$ORD6"; do
  sudo -n ip -n "$INET_NS" -6 addr add "$addr/128" dev lo nodad
  sudo -n ip -n "$CLIENT_NS" -6 route add "$addr/128" via 2001:db8:10::1 dev wan0
done
sudo -n ip -n "$CLIENT_NS" addr add 10.77.0.2/24 dev piabazzite
sudo -n ip -n "$VPN_NS" addr add 10.77.0.1/24 dev vpn0
sudo -n ip -n "$VPN_NS" addr add 192.0.4.1/32 dev lo
sudo -n ip -n "$CLIENT_NS" -6 addr add fd42:5049:4300::2/64 dev piabazzite nodad
sudo -n ip -n "$VPN_NS" -6 addr add fd42:5049:4300::1/64 dev vpn0 nodad
sudo -n ip -n "$VPN_NS" -6 addr add 2001:db8:300::1/128 dev lo nodad
sudo -n ip -n "$CLIENT_NS" link set piabazzite up
sudo -n ip -n "$VPN_NS" link set vpn0 up
sudo -n ip -n "$CLIENT_NS" route add 192.0.4.1/32 via 10.77.0.1 dev piabazzite
sudo -n ip -n "$CLIENT_NS" -6 route add 2001:db8:300::1/128 via fd42:5049:4300::1 dev piabazzite
pass "temporary two-uplink namespace laboratory created"
printf '\n'

printf '%s\n' '--- Deliberately denied authorization through the real client ---'
pkcheck --revoke-temp >/dev/null 2>&1 || true
printf 'A graphical Polkit dialog should appear. Click Cancel / Abbrechen.\n'
set +e
deny_output="$(timeout 70s python3 -I "$DRIVER" "$BRIDGE_TARGET" status 2>&1)"
deny_code=$?
set -e
printf '%s\n' "$deny_output"
if [[ $deny_code -eq 20 ]] && python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["kind"]=="authorization-denied"' <<<"$deny_output"; then
  pass "real client classified the denied Polkit request"
elif [[ $deny_code -eq 124 ]]; then
  fail "authorization denial timed out"
else
  fail "authorization denial returned unexpected client result $deny_code"
fi
if sudo -n ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "denied client request created a namespace table"
else
  pass "denied client request changed no firewall state"
fi
printf '\n'

printf '%s\n' '--- Authorized enable and status through the real client ---'
printf 'A graphical Polkit password dialog should appear now. Authorize this request.\n'
set +e
enable_output="$(client_call enable 2>&1)"; enable_code=$?
set -e
printf '%s\n' "$enable_output"
if [[ $enable_code -eq 0 ]] && validate_client_status enable active true <<<"$enable_output"; then
  pass "client accepted only the helper-verified active enable result"
else
  fail "client enable did not return verified active protection"
fi
status_output="$(client_call status 2>&1)" || true
if validate_client_status status active true <<<"$status_output"; then
  pass "separate client status call observed verified active protection"
else
  printf '%s\n' "$status_output"; fail "client status verification failed"
fi
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then fail "host table was created"; else pass "host firewall still has no helper table"; fi
expect_blocked "ordinary IPv4 is blocked" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
expect_blocked "ordinary IPv6 is blocked" sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 "$ORD6"
expect_success "simulated VPN IPv4 remains allowed" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.4.1
expect_success "simulated VPN IPv6 remains allowed" sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:300::1
printf '\n'

printf '%s\n' '--- Atomic updates through the real client ---'
set_output="$(client_call set-endpoints 2>&1)" || true
if validate_client_status set-endpoints active true <<<"$set_output"; then pass "client completed atomic endpoint replacement"; else printf '%s\n' "$set_output"; fail "client endpoint replacement failed"; fi
interface_output="$(client_call set-interfaces 2>&1)" || true
if validate_client_status set-interfaces active true <<<"$interface_output"; then pass "client completed atomic interface replacement"; else printf '%s\n' "$interface_output"; fail "client interface replacement failed"; fi
for addr in "$OLD4" "$NEW4" "$ORD4"; do sudo -n ip -n "$CLIENT_NS" route replace "$addr/32" via 192.0.3.1 dev lan0; done
for addr in "$OLD6" "$NEW6" "$ORD6"; do sudo -n ip -n "$CLIENT_NS" -6 route replace "$addr/128" via 2001:db8:11::1 dev lan0; done
expect_blocked "ordinary IPv4 remains blocked after interface update" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
add_output="$(client_call add-endpoint 2>&1)" || true
if validate_client_status add-endpoint active true <<<"$add_output"; then pass "client added one endpoint"; else fail "client add-endpoint failed"; fi
remove_output="$(client_call remove-endpoint 2>&1)" || true
if validate_client_status remove-endpoint active true <<<"$remove_output"; then pass "client removed one endpoint"; else fail "client remove-endpoint failed"; fi
printf '\n'

printf '%s\n' '--- Real subprocess invalid-response and timeout classification ---'
set +e
invalid_output="$(python3 -I "$DRIVER" "$INVALID_PROBE" invalid-response-probe "$PROCESS_SHIM" 2>&1)"; invalid_code=$?
set -e
printf '%s\n' "$invalid_output"
if [[ $invalid_code -eq 22 ]] && python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["kind"]=="invalid-response"' <<<"$invalid_output"; then
  pass "real client rejected malformed subprocess output"
else
  fail "invalid-response probe was not classified correctly"
fi
set +e
timeout_output="$(python3 -I "$DRIVER" "$TIMEOUT_PROBE" timeout-probe "$PROCESS_SHIM" 2>&1)"; timeout_code=$?
set -e
printf '%s\n' "$timeout_output"
if [[ $timeout_code -eq 21 ]] && python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["kind"]=="timeout"' <<<"$timeout_output"; then
  pass "real client reported subprocess timeout separately"
else
  fail "timeout probe was not classified correctly"
fi
sleep 0.2
if pgrep -f "pia-bazzite-stage3-timeout-prob[e]" >/dev/null 2>&1; then fail "timeout probe process remained alive"; else pass "timed-out probe process was terminated"; fi
printf '\n'

printf '%s\n' '--- Deliberate disable through the real client ---'
disable_output="$(client_call disable 2>&1)" || true
printf '%s\n' "$disable_output"
if validate_client_status disable disabled false <<<"$disable_output"; then
  pass "client accepted only the verified disabled result"
else
  fail "client disable verification failed"
fi
if sudo -n ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" >/dev/null 2>&1; then fail "namespace table remained after disable"; else pass "namespace table is absent after disable"; fi
expect_success "ordinary IPv4 works after deliberate disable" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
printf '\n'

printf '%s\n' '--- Explicit cleanup and host safety verification ---'
cleanup
NAMESPACES=0; BRIDGE_INSTALLED=0; PROBES_INSTALLED=0; SHIM_INSTALLED=0; INSTALLED=0
if ip netns list | grep -q "^pia-h3-.*-$TOKEN"; then fail "temporary namespace remained"; else pass "all temporary namespaces were removed"; fi
if [[ -e "$BRIDGE_TARGET" || -L "$BRIDGE_TARGET" ]]; then fail "test bridge remained installed"; else pass "test bridge was removed"; fi
if [[ -e "$INVALID_PROBE" || -L "$INVALID_PROBE" || -e "$TIMEOUT_PROBE" || -L "$TIMEOUT_PROBE" ]]; then fail "test probe remained installed"; else pass "test probes were removed"; fi
if [[ -e "$PROCESS_SHIM" || -L "$PROCESS_SHIM" ]]; then fail "process shim remained installed"; else pass "process shim was removed"; fi
if [[ -e "$TARGET_DIR/pia-bazzite-kill-switch-helper" ]]; then fail "restricted helper remained installed"; else pass "restricted helper was removed"; fi
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then fail "host helper table exists after test"; else pass "host firewall remains free of the helper table"; fi
printf '\n--- Result ---\nPASS: %d\nFAIL: %d\n' "$PASS" "$FAIL"
if [[ $FAIL -eq 0 ]]; then
  printf 'ALL STAGE-3B REAL-CLIENT INTEGRATION TESTS PASSED\n'
  printf 'Report: %s\n' "$REPORT"
  exit 0
fi
printf 'STAGE-3B REAL-CLIENT INTEGRATION TEST FAILED\n'
exit 1
