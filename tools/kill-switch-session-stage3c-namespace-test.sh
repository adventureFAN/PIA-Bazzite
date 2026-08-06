#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
BRIDGE_SOURCE="$ROOT/tools/pia-bazzite-stage3c-session-netns-bridge.py"
DRIVER="$ROOT/tools/pia-bazzite-stage3c-session-driver.py"
TARGET_DIR="/usr/local/libexec/pia-bazzite"
TOKEN="$$"
CLIENT_NS="pia-h3c-client-$TOKEN"
INET_NS="pia-h3c-inet-$TOKEN"
VPN_NS="pia-h3c-vpn-$TOKEN"
BRIDGE_TARGET="$TARGET_DIR/pia-bazzite-stage3c-session-netns-bridge-$TOKEN"
TABLE="pia_bazzite_killswitch"
REPORT_DIR="$ROOT/test-results/kill-switch/stage3-client"
REPORT="$REPORT_DIR/pia-kill-switch-session-stage3c-namespace-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

PASS=0
FAIL=0
INSTALLED=0
BRIDGE_INSTALLED=0
NAMESPACES=0
CONTROLLER_PID=""
CONTROLLER_IN=""
CONTROLLER_OUT=""
SESSION_PID=""

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
  if [[ -n "$CONTROLLER_PID" ]] && kill -0 "$CONTROLLER_PID" >/dev/null 2>&1; then
    if [[ -n "$CONTROLLER_IN" ]]; then printf 'close\n' >&"$CONTROLLER_IN" 2>/dev/null || true; fi
    sleep 0.2
    kill "$CONTROLLER_PID" >/dev/null 2>&1 || true
    wait "$CONTROLLER_PID" >/dev/null 2>&1 || true
  fi
  if [[ $NAMESPACES -eq 1 ]]; then
    sudo -n ip netns exec "$CLIENT_NS" nft destroy table inet "$TABLE" >/dev/null 2>&1 || true
    sudo -n ip netns del "$CLIENT_NS" >/dev/null 2>&1 || true
    sudo -n ip netns del "$INET_NS" >/dev/null 2>&1 || true
    sudo -n ip netns del "$VPN_NS" >/dev/null 2>&1 || true
  fi
  if [[ $BRIDGE_INSTALLED -eq 1 ]]; then
    sudo -n rm -f -- "$BRIDGE_TARGET" >/dev/null 2>&1 || true
  fi
  if [[ $INSTALLED -eq 1 ]]; then
    sudo -n "$INSTALLER" uninstall >/dev/null 2>&1 || true
  fi
  sudo -n rm -f /run/lock/pia-bazzite-kill-switch-helper.lock >/dev/null 2>&1 || true
}
trap cleanup EXIT

expect_success() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi
}
expect_blocked() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then fail "$label"; else pass "$label"; fi
}

validate_ready() {
  python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p["controller_ok"] is True
assert p["event"] == "ready"
assert isinstance(p["session_pid"], int) and p["session_pid"] > 1
print(p["session_pid"])
'
}

validate_status() {
  local action="$1" state="$2" active="$3" expected_pid="$4"
  python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p["controller_ok"] is True
assert p["action"] == sys.argv[1]
assert p["state"] == sys.argv[2]
assert p["verified"] is True
assert p["protection_active"] is (sys.argv[3] == "true")
assert p["session_pid"] == int(sys.argv[4])
' "$action" "$state" "$active" "$expected_pid"
}

controller_call() {
  local operation="$1" response
  printf '%s\n' "$operation" >&"$CONTROLLER_IN"
  if ! IFS= read -r -t 25 -u "$CONTROLLER_OUT" response; then
    printf '{"controller_ok":false,"kind":"controller-timeout"}\n'
    return 1
  fi
  printf '%s\n' "$response"
}

printf 'PIA Bazzite stage-3C single-authorization session test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'One authorized Polkit launch opens a restricted root broker.\n'
printf 'All later helper operations reuse that same broker process inside temporary namespaces.\n\n'

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
if sudo -n "$INSTALLER" install; then INSTALLED=1; pass "helper and session broker installed"; else fail "helper installation failed"; fi
if [[ -e "$BRIDGE_TARGET" || -L "$BRIDGE_TARGET" ]]; then
  fail "tokenized session bridge path already exists"
elif sudo -n install -o root -g root -m 0755 -- "$BRIDGE_SOURCE" "$BRIDGE_TARGET"; then
  BRIDGE_INSTALLED=1; pass "tokenized root-owned session bridge installed"
else
  fail "session bridge installation failed"
fi

sudo -n ip netns add "$CLIENT_NS"
sudo -n ip netns add "$INET_NS"
sudo -n ip netns add "$VPN_NS"
NAMESPACES=1
sudo -n ip link add "c3wA$TOKEN" type veth peer name "c3wB$TOKEN"
sudo -n ip link set "c3wA$TOKEN" netns "$CLIENT_NS"
sudo -n ip link set "c3wB$TOKEN" netns "$INET_NS"
sudo -n ip -n "$CLIENT_NS" link set "c3wA$TOKEN" name wan0
sudo -n ip -n "$INET_NS" link set "c3wB$TOKEN" name inet-wan0
sudo -n ip link add "c3lA$TOKEN" type veth peer name "c3lB$TOKEN"
sudo -n ip link set "c3lA$TOKEN" netns "$CLIENT_NS"
sudo -n ip link set "c3lB$TOKEN" netns "$INET_NS"
sudo -n ip -n "$CLIENT_NS" link set "c3lA$TOKEN" name lan0
sudo -n ip -n "$INET_NS" link set "c3lB$TOKEN" name inet-lan0
sudo -n ip link add "c3vA$TOKEN" type veth peer name "c3vB$TOKEN"
sudo -n ip link set "c3vA$TOKEN" netns "$CLIENT_NS"
sudo -n ip link set "c3vB$TOKEN" netns "$VPN_NS"
sudo -n ip -n "$CLIENT_NS" link set "c3vA$TOKEN" name piabazzite
sudo -n ip -n "$VPN_NS" link set "c3vB$TOKEN" name vpn0
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

printf '%s\n' '--- Deliberately denied session authorization ---'
pkcheck --revoke-temp >/dev/null 2>&1 || true
printf 'A graphical Polkit dialog should appear. Click Cancel / Abbrechen.\n'
set +e
deny_output="$(timeout 70s python3 -I "$DRIVER" "$BRIDGE_TARGET" denial-probe 2>&1)"
deny_code=$?
set -e
printf '%s\n' "$deny_output"
if [[ $deny_code -eq 20 ]] && python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["kind"]=="authorization-denied"' <<<"$deny_output"; then
  pass "session client classified the denied Polkit launch"
elif [[ $deny_code -eq 124 ]]; then
  fail "session authorization denial timed out"
else
  fail "session denial returned unexpected result $deny_code"
fi
if sudo -n ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "denied session launch created a namespace table"
else
  pass "denied session launch changed no firewall state"
fi
printf '\n'

printf '%s\n' '--- One authorized broker for the complete helper workflow ---'
printf 'One graphical Polkit password dialog should appear now. Authorize it once.\n'
printf 'No further Polkit dialogs should appear during the operations below.\n'
coproc H3C_CONTROLLER { python3 -I "$DRIVER" "$BRIDGE_TARGET" session; }
CONTROLLER_PID="$H3C_CONTROLLER_PID"
CONTROLLER_OUT="${H3C_CONTROLLER[0]}"
CONTROLLER_IN="${H3C_CONTROLLER[1]}"
if IFS= read -r -t 70 -u "$CONTROLLER_OUT" ready_output; then
  printf '%s\n' "$ready_output"
  if SESSION_PID="$(validate_ready <<<"$ready_output")"; then
    pass "one Polkit authorization opened the restricted broker"
  else
    fail "session controller did not return a valid ready frame"
  fi
else
  fail "session controller did not become ready"
fi

for spec in \
  "enable active true" \
  "status active true" \
  "set-endpoints active true" \
  "set-interfaces active true" \
  "add-endpoint active true" \
  "remove-endpoint active true"
do
  read -r operation state active <<<"$spec"
  output="$(controller_call "$operation")" || true
  printf '%s\n' "$output"
  if [[ -n "$SESSION_PID" ]] && validate_status "$operation" "$state" "$active" "$SESSION_PID" <<<"$output"; then
    pass "$operation reused broker PID $SESSION_PID without another pkexec launch"
  else
    fail "$operation did not return a valid same-session response"
  fi
  if [[ "$operation" == "enable" ]]; then
    expect_blocked "ordinary IPv4 is blocked" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
    expect_blocked "ordinary IPv6 is blocked" sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 "$ORD6"
    expect_success "simulated VPN IPv4 remains allowed" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.4.1
    expect_success "simulated VPN IPv6 remains allowed" sudo -n ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:300::1
  elif [[ "$operation" == "set-interfaces" ]]; then
    for addr in "$OLD4" "$NEW4" "$ORD4"; do sudo -n ip -n "$CLIENT_NS" route replace "$addr/32" via 192.0.3.1 dev lan0; done
    for addr in "$OLD6" "$NEW6" "$ORD6"; do sudo -n ip -n "$CLIENT_NS" -6 route replace "$addr/128" via 2001:db8:11::1 dev lan0; done
    expect_blocked "ordinary IPv4 remains blocked after interface update" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"
  fi
done

output="$(controller_call disable)" || true
printf '%s\n' "$output"
if [[ -n "$SESSION_PID" ]] && validate_status disable disabled false "$SESSION_PID" <<<"$output"; then
  pass "disable reused the same broker and verified table removal"
else
  fail "disable did not return a valid same-session response"
fi
if sudo -n ip netns exec "$CLIENT_NS" nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "namespace table remained after disable"
else
  pass "namespace table is absent after disable"
fi
expect_success "ordinary IPv4 works after deliberate disable" sudo -n ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 "$ORD4"

close_output="$(controller_call close)" || true
printf '%s\n' "$close_output"
if python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["controller_ok"] is True; assert p["event"]=="closed"; assert p["session_pid"]==int(sys.argv[1])' "$SESSION_PID" <<<"$close_output"; then
  pass "client explicitly closed the privileged broker"
else
  fail "session close response was invalid"
fi
wait "$CONTROLLER_PID" || fail "session controller exited unsuccessfully"
CONTROLLER_PID=""
printf '\n'

printf '%s\n' '--- Explicit cleanup and host safety verification ---'
cleanup
NAMESPACES=0; BRIDGE_INSTALLED=0; INSTALLED=0
if ip netns list | grep -q "^pia-h3c-.*-$TOKEN"; then fail "temporary namespace remained"; else pass "all temporary namespaces were removed"; fi
if [[ -e "$BRIDGE_TARGET" || -L "$BRIDGE_TARGET" ]]; then fail "test session bridge remained installed"; else pass "test session bridge was removed"; fi
if [[ -e "$TARGET_DIR/pia-bazzite-kill-switch-helper" || -e "$TARGET_DIR/pia-bazzite-kill-switch-session" ]]; then fail "helper installation remained"; else pass "helper and session broker were removed"; fi
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then fail "host helper table exists after test"; else pass "host firewall remains free of the helper table"; fi
printf '\n--- Result ---\nPASS: %d\nFAIL: %d\n' "$PASS" "$FAIL"
if [[ $FAIL -eq 0 ]]; then
  printf 'ALL STAGE-3C SINGLE-AUTHORIZATION SESSION TESTS PASSED\n'
  printf 'Report: %s\n' "$REPORT"
  exit 0
fi
printf 'STAGE-3C SINGLE-AUTHORIZATION SESSION TEST FAILED\n'
exit 1
