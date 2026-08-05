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
REPORT="$REPORT_DIR/pia-kill-switch-polkit-stage2-helper-namespace-test.txt"
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
WAN_A="h2wa$SUFFIX"
WAN_B="h2wb$SUFFIX"
VPN_A="h2va$SUFFIX"
VPN_B="h2vb$SUFFIX"
INSTALLED=0
BRIDGE_INSTALLED=0
NAMESPACES=0
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }

cleanup() {
  set +e
  if [[ $NAMESPACES -eq 1 ]]; then
    sudo ip netns exec "$CLIENT_NS" nft destroy table inet "$TABLE" >/dev/null 2>&1 || true
    sudo ip netns del "$CLIENT_NS" >/dev/null 2>&1 || true
    sudo ip netns del "$INET_NS" >/dev/null 2>&1 || true
    sudo ip netns del "$VPN_NS" >/dev/null 2>&1 || true
    sudo ip link del "$WAN_A" >/dev/null 2>&1 || true
    sudo ip link del "$VPN_A" >/dev/null 2>&1 || true
  fi
  sudo rm -f -- "$LOCK" >/dev/null 2>&1 || true
  if [[ $BRIDGE_INSTALLED -eq 1 ]]; then
    if [[ -f "$BRIDGE_TARGET" && ! -L "$BRIDGE_TARGET" ]] \
        && [[ "$(stat -c '%u:%g' -- "$BRIDGE_TARGET" 2>/dev/null)" == "0:0" ]]; then
      sudo rm -f -- "$BRIDGE_TARGET" >/dev/null 2>&1 || true
    fi
  fi
  if [[ $INSTALLED -eq 1 ]]; then
    sudo "$INSTALLER" uninstall >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM HUP

ns_root() {
  sudo ip netns exec "$CLIENT_NS" "$@"
}

host_user_pkexec() {
  "$PKEXEC" --disable-internal-agent "$BRIDGE_TARGET" "$CLIENT_NS"
}
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

printf 'PIA Bazzite stage-2C installed-helper Polkit namespace test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'The real helper is installed root-owned, but it still manages only the fixed\n'
printf 'stage-1 test table inside temporary network namespaces.\n'
printf 'The host firewall, NetworkManager, and PIA profile are not changed.\n\n'

printf '%s\n' '--- Preconditions and root-owned installation ---'
sudo -v
if pgrep -u "$USER_ID" -f 'polkit.*agent|polkit-kde' >/dev/null 2>&1; then
  pass "graphical Polkit authentication agent is running"
else
  fail "no graphical Polkit authentication agent detected"
fi

if sudo nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "fixed helper test table already exists on the host"
else
  pass "host does not contain the fixed helper test table"
fi

if sudo "$INSTALLER" install; then
  INSTALLED=1
  pass "restricted helper installed under the fixed root-owned path"
else
  fail "restricted helper installation failed"
fi

if [[ -e "$BRIDGE_TARGET" || -L "$BRIDGE_TARGET" ]]; then
  fail "fixed stage-2 namespace bridge path already exists"
elif sudo /usr/bin/install -o root -g root -m 0755 -- "$BRIDGE_SOURCE" "$BRIDGE_TARGET"; then
  BRIDGE_INSTALLED=1
  pass "fixed root-owned stage-2 namespace bridge installed"
else
  fail "stage-2 namespace bridge installation failed"
fi

if [[ -f "$TARGET" && ! -L "$TARGET" ]] \
    && [[ "$(stat -c '%u:%g:%a' -- "$TARGET")" == "0:0:755" ]]; then
  pass "installed launcher is root:root mode 0755"
else
  fail "installed launcher ownership or mode is unsafe"
fi

set +e
direct_output="$("$TARGET" status 2>&1)"
direct_code=$?
set -e
if [[ $direct_code -eq 3 ]] && grep -q '"error": "privilege"' <<<"$direct_output"; then
  pass "direct unprivileged execution is refused"
else
  fail "direct unprivileged execution was not refused correctly"
fi
printf '\n'

if [[ $FAIL -ne 0 ]]; then
  echo "Preconditions failed; namespace and Polkit mutation test was not started."
else
  printf '%s\n' '--- Create isolated network lab ---'
  sudo ip netns add "$CLIENT_NS"
  sudo ip netns add "$INET_NS"
  sudo ip netns add "$VPN_NS"
  NAMESPACES=1

  sudo ip link add "$WAN_A" type veth peer name "$WAN_B"
  sudo ip link set "$WAN_A" netns "$CLIENT_NS"
  sudo ip link set "$WAN_B" netns "$INET_NS"
  sudo ip -n "$CLIENT_NS" link set "$WAN_A" name wan0
  sudo ip -n "$INET_NS" link set "$WAN_B" name inet0

  sudo ip link add "$VPN_A" type veth peer name "$VPN_B"
  sudo ip link set "$VPN_A" netns "$CLIENT_NS"
  sudo ip link set "$VPN_B" netns "$VPN_NS"
  sudo ip -n "$CLIENT_NS" link set "$VPN_A" name piabazzite
  sudo ip -n "$VPN_NS" link set "$VPN_B" name vpn0

  for namespace in "$CLIENT_NS" "$INET_NS" "$VPN_NS"; do
    sudo ip -n "$namespace" link set lo up
  done

  sudo ip -n "$CLIENT_NS" addr add 198.51.100.2/24 dev wan0
  sudo ip -n "$INET_NS" addr add 198.51.100.1/24 dev inet0
  sudo ip -n "$INET_NS" addr add 203.0.113.1/32 dev inet0
  sudo ip -n "$CLIENT_NS" link set wan0 up
  sudo ip -n "$INET_NS" link set inet0 up
  sudo ip -n "$CLIENT_NS" route add default via 198.51.100.1 dev wan0

  sudo ip -n "$CLIENT_NS" -6 addr add 2001:db8:10::2/64 dev wan0 nodad
  sudo ip -n "$INET_NS" -6 addr add 2001:db8:10::1/64 dev inet0 nodad
  sudo ip -n "$INET_NS" -6 addr add 2001:db8:20::1/128 dev inet0 nodad
  sudo ip -n "$CLIENT_NS" -6 route add default via 2001:db8:10::1 dev wan0

  sudo ip -n "$CLIENT_NS" addr add 10.77.0.2/24 dev piabazzite
  sudo ip -n "$VPN_NS" addr add 10.77.0.1/24 dev vpn0
  sudo ip -n "$VPN_NS" addr add 192.0.2.1/32 dev vpn0
  sudo ip -n "$CLIENT_NS" link set piabazzite up
  sudo ip -n "$VPN_NS" link set vpn0 up
  sudo ip -n "$CLIENT_NS" route add 192.0.2.1/32 via 10.77.0.1 dev piabazzite

  sudo ip -n "$CLIENT_NS" -6 addr add fd42:5049:4200::2/64 dev piabazzite nodad
  sudo ip -n "$VPN_NS" -6 addr add fd42:5049:4200::1/64 dev vpn0 nodad
  sudo ip -n "$VPN_NS" -6 addr add 2001:db8:30::1/128 dev vpn0 nodad
  sudo ip -n "$CLIENT_NS" -6 route add 2001:db8:30::1/128 \
    via fd42:5049:4200::1 dev piabazzite
  pass "temporary namespaces and veth interfaces were created"
  printf '\n'

  printf '%s\n' '--- Baseline traffic ---'
  expect_success "ordinary IPv4 works before helper protection" \
    sudo ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
  expect_success "ordinary IPv6 works before helper protection" \
    sudo ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
  expect_success "simulated VPN IPv4 route works" \
    sudo ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
  expect_success "simulated VPN IPv6 route works" \
    sudo ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1
  printf '\n'

  printf '%s\n' '--- Installed helper through graphical Polkit ---'
  echo "A graphical Polkit password dialog should appear now."
  set +e
  authorized_output="$(host_user_pkexec 2>&1)"
  authorized_code=$?
  set -e
  printf '%s\n' "$authorized_output"

  if [[ $authorized_code -eq 0 ]]; then
    pass "desktop-session pkexec authorized the fixed bridge and helper"
  elif [[ $authorized_code -eq 127 ]]; then
    fail "no graphical Polkit agent was associated with the desktop request"
  else
    fail "pkexec/bridge/helper returned exit code $authorized_code"
  fi

  if "$PYTHON" -c '
import json, sys
p=json.loads(sys.stdin.read())
assert p["ok"] is True
assert p["action"] == "enable"
assert p["state"] == "active"
assert p["verified"] is True
assert p["table"] == "pia_bazzite_killswitch_helper_test"
' <<<"$authorized_output"; then
    pass "helper JSON confirms applied and verified protection"
  else
    fail "helper JSON verification failed"
  fi

  if ns_root nft list table inet "$TABLE" >/dev/null 2>&1; then
    pass "fixed test table exists only inside the client namespace"
  else
    fail "fixed test table is missing inside the client namespace"
  fi

  if sudo nft list table inet "$TABLE" >/dev/null 2>&1; then
    fail "helper test table was created on the host"
  else
    pass "host firewall still has no helper test table"
  fi
  printf '\n'

  printf '%s\n' '--- Traffic under installed-helper protection ---'
  expect_blocked "ordinary IPv4 is blocked" \
    sudo ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 203.0.113.1
  expect_blocked "ordinary IPv6 is blocked" \
    sudo ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:20::1
  expect_success "simulated VPN IPv4 remains allowed" \
    sudo ip netns exec "$CLIENT_NS" ping -4 -c 1 -W 1 192.0.2.1
  expect_success "simulated VPN IPv6 remains allowed" \
    sudo ip netns exec "$CLIENT_NS" ping -6 -c 1 -W 1 2001:db8:30::1
  printf '\n'

  printf '%s\n' '--- Explicit isolated cleanup ---'
  if ns_root nft destroy table inet "$TABLE"; then
    pass "test harness removed the fixed namespace table"
  else
    fail "test harness could not remove the fixed namespace table"
  fi
  if ns_root nft list table inet "$TABLE" >/dev/null 2>&1; then
    fail "fixed namespace table remains after cleanup"
  else
    pass "fixed namespace table is absent after cleanup"
  fi
fi

printf '\n%s\n' '--- Remove root-owned stage-2 namespace bridge ---'
if [[ $BRIDGE_INSTALLED -eq 1 ]]; then
  if [[ -f "$BRIDGE_TARGET" && ! -L "$BRIDGE_TARGET" ]] \
      && [[ "$(stat -c '%u:%g' -- "$BRIDGE_TARGET")" == "0:0" ]]; then
    if sudo rm -f -- "$BRIDGE_TARGET"; then
      BRIDGE_INSTALLED=0
      pass "root-owned stage-2 namespace bridge was removed"
    else
      fail "root-owned stage-2 namespace bridge could not be removed"
    fi
  else
    fail "stage-2 namespace bridge ownership or type became unsafe"
  fi
fi
if [[ ! -e "$BRIDGE_TARGET" && ! -L "$BRIDGE_TARGET" ]]; then
  pass "fixed stage-2 namespace bridge is absent"
else
  fail "fixed stage-2 namespace bridge remains"
fi

printf '\n%s\n' '--- Remove root-owned stage-2C installation ---'
if [[ $INSTALLED -eq 1 ]]; then
  if sudo "$INSTALLER" uninstall; then
    INSTALLED=0
    pass "root-owned installed helper was removed"
  else
    fail "root-owned installed helper could not be removed"
  fi
fi
sudo rm -f -- "$LOCK" >/dev/null 2>&1 || true
if [[ ! -e "$TARGET" ]]; then
  pass "fixed installed launcher is absent"
else
  fail "fixed installed launcher remains"
fi

printf '\n%s\n' '--- Result ---'
printf 'PASS: %d\n' "$PASS"
printf 'FAIL: %d\n' "$FAIL"
if [[ $FAIL -eq 0 ]]; then
  printf 'ALL STAGE-2C INSTALLED-HELPER POLKIT TESTS PASSED\n'
  printf 'Report: %s\n' "$REPORT"
  exit 0
fi
printf 'STAGE-2C INSTALLED-HELPER POLKIT TEST FAILED\n'
printf 'Report: %s\n' "$REPORT"
exit 1
