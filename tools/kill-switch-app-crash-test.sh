#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$PROJECT_ROOT/pia-kill-switch-app-crash-test.txt}"

TABLE="pia_bazzite_killswitch_crash_test"
CHAIN="output"
RESET_UNIT="pia-bazzite-killswitch-crash-test-reset"
VPN_INTERFACE="piabazzite"
RESET_SECONDS=240

PASSED=0
WARNINGS=0
FAILURES=0
TABLE_CREATED=0
RESET_SCHEDULED=0
CLEANUP_RUNNING=0

PROFILE_UUID=""
PROFILE_NAME=""
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""
FWMARK=""
ROUTE_DEVICE=""

NFT_BIN="$(command -v nft || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-crash.XXXXXX.nft)"
PID_FILE="$(mktemp /tmp/pia-bazzite-pids.XXXXXX.txt)"

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

active_profile_line() {
  nmcli -t -f UUID,NAME,TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: '$3 == "wireguard" && $4 == "piabazzite" {
        print
        exit
      }'
}

vpn_is_active() {
  [[ -n "$(active_profile_line)" ]] \
    && ip link show "$VPN_INTERFACE" >/dev/null 2>&1
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

udp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"

  python3 - "$family" "$address" "$port" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text = sys.argv[1:4]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET

with socket.socket(family, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)
    sock.connect((address, int(port_text)))
    sock.send(b"PIA-BAZZITE-APP-CRASH-TEST")
PY
}

expect_success() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    pass "$description"
    return 0
  fi

  fail "$description"
  return 1
}

expect_blocked() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    fail "$description (traffic unexpectedly succeeded)"
    return 1
  fi

  pass "$description"
  return 0
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

wait_for_vpn_down() {
  local attempt
  for attempt in $(seq 1 30); do
    if ! vpn_is_active; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_recent_handshake() {
  local attempt timestamp now age
  for attempt in $(seq 1 50); do
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

find_app_processes() {
  python3 - "$$" "$PPID" <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import sys

excluded = {int(value) for value in sys.argv[1:] if value.isdigit()}

# Exclude the complete ancestor chain of this test script.
current = os.getppid()
while current > 1 and current not in excluded:
    excluded.add(current)
    try:
        status = Path(f"/proc/{current}/status").read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        break

    parent = 0
    for line in status.splitlines():
        if line.startswith("PPid:"):
            try:
                parent = int(line.split()[1])
            except (IndexError, ValueError):
                parent = 0
            break

    if parent <= 1 or parent == current:
        break
    current = parent

matches: list[tuple[int, str]] = []

for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue

    pid = int(proc.name)
    if pid in excluded:
        continue

    try:
        raw = (proc / "cmdline").read_bytes()
        if not raw:
            continue
        args = [
            item.decode("utf-8", errors="replace")
            for item in raw.split(b"\0")
            if item
        ]
        exe = os.path.basename(os.readlink(proc / "exe"))
        cwd = os.readlink(proc / "cwd")
    except OSError:
        continue

    joined = " ".join(args)
    basenames = [os.path.basename(arg) for arg in args]

    source_app = (
        any(name == "main.py" for name in basenames)
        and (
            cwd.rstrip("/").endswith("/PIA-Bazzite")
            or any("PIA-Bazzite" in arg for arg in args)
        )
    )
    pyinstaller_app = (
        exe == "PIA-Bazzite"
        or any(name == "PIA-Bazzite" for name in basenames)
    )
    appimage_wrapper = any(
        name.startswith("PIA-Bazzite")
        and name.endswith(".AppImage")
        for name in basenames
    )

    if source_app or pyinstaller_app or appimage_wrapper:
        description = joined
        if len(description) > 180:
            description = description[:177] + "..."
        matches.append((pid, description))

for pid, description in sorted(set(matches)):
    print(f"{pid}\t{description}")
PY
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

reconnect_after_cleanup() {
  if [[ -z "$PROFILE_UUID" ]] || vpn_is_active; then
    return
  fi

  printf '%s\n' \
    'Cleanup: attempting to restore the original PIA WireGuard connection ...'
  timeout 65s nmcli connection up uuid "$PROFILE_UUID" >/dev/null 2>&1 \
    || warn "automatic PIA reconnection during cleanup did not succeed"
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
  reconnect_after_cleanup
  rm -f "$TMP_RULESET" "$PID_FILE"

  if (( exit_code != 0 )); then
    printf '\nThe app-crash test exited early.\n'
    printf 'Its temporary nftables table and safety timer were removed.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite guarded application-crash kill-switch test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'This test WILL terminate the running PIA Bazzite application with SIGKILL.' \
  'That is an intentional hard crash: the app gets no cleanup opportunity.' \
  '' \
  'The NetworkManager WireGuard connection should initially remain active.' \
  'The test then removes the tunnel externally and verifies that the independent' \
  'nftables kill switch still blocks IPv4, IPv6, and direct DNS traffic.' \
  '' \
  "A root-owned automatic reset deletes the test table after ${RESET_SECONDS} seconds." \
  '' \
  'Emergency command in a second terminal:' \
  "  sudo nft delete table inet ${TABLE}" \
  '' \
  'After the test, the WireGuard tunnel is restored, but the GUI remains closed.' \
  'Launch PIA Bazzite again from your Favorites afterward.'

read -r -p 'Type CRASH exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "CRASH" ]]; then
  printf 'Cancelled. Nothing was changed.\n'
  exit 0
fi

printf '\n%s\n' '--- Preflight ---'

for tool in nmcli wg ip nft systemctl systemd-run python3 sudo timeout kill; do
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

ACTIVE_LINE="$(active_profile_line)"
if [[ -z "$ACTIVE_LINE" ]]; then
  fail "PIA Bazzite is not connected"
  exit 1
fi

IFS=: read -r PROFILE_UUID PROFILE_NAME PROFILE_TYPE PROFILE_DEVICE \
  <<<"$ACTIVE_LINE"
pass "PIA Bazzite WireGuard profile is active"
printf 'Profile: %s\n' "$PROFILE_NAME"
printf 'Interface: %s\n' "$PROFILE_DEVICE"

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

ROUTE_DEVICE="$(
  awk '{
    for (i = 1; i <= NF; i++) {
      if ($i == "dev" && i < NF) {
        print $(i + 1)
        exit
      }
    }
  }' <<<"$ROUTE_LINE"
)"

if [[ -z "$ROUTE_DEVICE" || "$ROUTE_DEVICE" == "$VPN_INTERFACE" ]]; then
  fail "the physical route to the WireGuard endpoint is unsafe or unknown"
  exit 1
fi
pass "the endpoint escape route uses $ROUTE_DEVICE"

find_app_processes >"$PID_FILE"

if [[ ! -s "$PID_FILE" ]]; then
  fail "no running PIA Bazzite application process was detected"
  printf '%s\n' \
    'Start PIA Bazzite from Favorites, connect it, and run the test again.'
  exit 1
fi

printf 'Detected PIA Bazzite process(es):\n'
while IFS=$'\t' read -r pid description; do
  printf '  PID %-7s %s\n' "$pid" "$description"
done <"$PID_FILE"
pass "at least one PIA Bazzite application process was detected"

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "a previous app-crash test table already exists"
  exit 1
fi
pass "no previous app-crash test table exists"

expect_success \
  "public IPv4 TCP connectivity works through the VPN before the crash" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Schedule the automatic safety reset ---'
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
    "$NFT_BIN" delete table inet "$TABLE"; then
  RESET_SCHEDULED=1
else
  fail "the automatic reset timer could not be created"
  exit 1
fi

if sudo -n systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  pass "automatic firewall reset is armed for ${RESET_SECONDS} seconds"
else
  fail "the automatic reset timer is not active"
  exit 1
fi

printf '\n%s\n' '--- Install the temporary kill-switch table atomically ---'

if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
  ENDPOINT_RULE="ip daddr $ENDPOINT_IP udp dport $ENDPOINT_PORT oifname \"$ROUTE_DEVICE\" counter accept comment \"WireGuard endpoint\""
else
  ENDPOINT_RULE="ip6 daddr $ENDPOINT_IP udp dport $ENDPOINT_PORT oifname \"$ROUTE_DEVICE\" counter accept comment \"WireGuard endpoint\""
fi

cat >"$TMP_RULESET" <<NFT
table inet $TABLE {
  chain $CHAIN {
    type filter hook output priority -100; policy accept;
    oifname "lo" counter accept comment "loopback"
    $ENDPOINT_RULE
    oifname "$VPN_INTERFACE" counter accept comment "VPN tunnel"
    counter reject with icmpx type admin-prohibited comment "block outside VPN"
  }
}
NFT

if sudo -n nft -f "$TMP_RULESET"; then
  TABLE_CREATED=1
  pass "temporary kill-switch table was installed"
else
  fail "the temporary kill-switch table could not be installed"
  exit 1
fi

expect_success \
  "IPv4 connectivity still works through piabazzite before the app crash" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Hard-crash the PIA Bazzite application ---'
printf '%s\n' \
  'The detected PIA Bazzite process will now be terminated with SIGKILL.' \
  'Its tray icon and window should disappear.'

read -r -p 'Type KILL exactly to send SIGKILL: ' KILL_CONFIRM
if [[ "$KILL_CONFIRM" != "KILL" ]]; then
  printf 'Cancelled before the crash. Cleaning up safely.\n'
  exit 0
fi

mapfile -t APP_PIDS < <(awk -F'\t' '{ print $1 }' "$PID_FILE")

if (( ${#APP_PIDS[@]} == 0 )); then
  fail "the application PID list unexpectedly became empty"
  exit 1
fi

KILL_ERRORS=0
for pid in "${APP_PIDS[@]}"; do
  if kill -KILL "$pid" 2>/dev/null; then
    printf 'Sent SIGKILL to PID %s\n' "$pid"
  else
    warn "PID $pid had already exited or could not be killed"
    KILL_ERRORS=$((KILL_ERRORS + 1))
  fi
done

sleep 2

SURVIVORS=0
for pid in "${APP_PIDS[@]}"; do
  if kill -0 "$pid" 2>/dev/null; then
    SURVIVORS=$((SURVIVORS + 1))
    printf 'Still running: PID %s\n' "$pid"
  fi
done

if (( SURVIVORS == 0 )); then
  pass "all detected PIA Bazzite application processes exited after SIGKILL"
else
  fail "$SURVIVORS detected PIA Bazzite process(es) survived SIGKILL"
fi

if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  pass "the kill-switch table remained active after the app crash"
else
  fail "the kill-switch table disappeared after the app crash"
  exit 1
fi

if vpn_is_active; then
  pass "the NetworkManager WireGuard tunnel remained active after the app crash"
else
  fail "the WireGuard tunnel disappeared immediately after the app crash"
fi

expect_success \
  "public IPv4 connectivity still works through the surviving VPN tunnel" \
  tcp_probe 4 1.1.1.1 443 5

printf '\n%s\n' '--- Remove the tunnel while the app remains crashed ---'

if timeout 35s nmcli connection down uuid "$PROFILE_UUID" >/dev/null 2>&1; then
  pass "NetworkManager accepted the external VPN disconnect"
else
  warn "nmcli returned an error while bringing the VPN down"
fi

if wait_for_vpn_down; then
  pass "piabazzite is now down while PIA Bazzite remains crashed"
else
  fail "piabazzite did not go down within 30 seconds"
fi

BLOCK_BEFORE="$(rule_packets "block outside VPN")"
[[ "$BLOCK_BEFORE" =~ ^[0-9]+$ ]] || BLOCK_BEFORE=0

expect_blocked \
  "IPv4 cannot fall back while the application is crashed" \
  tcp_probe 4 1.1.1.1 443 4

expect_blocked \
  "IPv6 cannot fall back while the application is crashed" \
  tcp_probe 6 2606:4700:4700::1111 443 4

expect_blocked \
  "direct DNS-like UDP is blocked while the application is crashed" \
  udp_probe 4 1.1.1.1 53

BLOCK_AFTER="$(rule_packets "block outside VPN")"
[[ "$BLOCK_AFTER" =~ ^[0-9]+$ ]] || BLOCK_AFTER=0

if (( BLOCK_AFTER > BLOCK_BEFORE )); then
  pass "the block-rule counter increased while the app was absent (${BLOCK_BEFORE} -> ${BLOCK_AFTER})"
else
  fail "the block-rule counter did not increase while the app was absent"
fi

printf '\n%s\n' '--- Reconnect WireGuard while the app remains closed ---'

if timeout 65s nmcli connection up uuid "$PROFILE_UUID" >/dev/null 2>&1; then
  pass "NetworkManager reactivated the PIA profile without the application"
else
  fail "NetworkManager could not reactivate the PIA profile"
fi

if wait_for_recent_handshake; then
  pass "WireGuard completed a fresh handshake while the application remained closed"
else
  fail "no recent WireGuard handshake appeared within 50 seconds"
fi

expect_success \
  "public IPv4 connectivity works again through the restored VPN" \
  tcp_probe 4 1.1.1.1 443 5

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
  fail "the automatic reset timer is still active"
else
  pass "the automatic reset timer was cancelled"
fi

if vpn_is_active; then
  pass "the PIA WireGuard tunnel is connected at the end"
else
  fail "the PIA WireGuard tunnel is not connected at the end"
fi

find_app_processes >"$PID_FILE"
if [[ -s "$PID_FILE" ]]; then
  warn "a PIA Bazzite application process is running again unexpectedly"
else
  pass "PIA Bazzite remains closed as expected after the crash test"
fi

printf '\n%s\n' '--- Result ---'
printf 'Passed: %d\n' "$PASSED"
printf 'Warnings: %d\n' "$WARNINGS"
printf 'Failures: %d\n' "$FAILURES"

if (( FAILURES == 0 )); then
  printf '\nALL APPLICATION-CRASH TESTS PASSED\n'
  printf 'The independent nftables kill switch survived a SIGKILL of PIA Bazzite,\n'
  printf 'blocked fallback traffic after the tunnel was removed, and allowed\n'
  printf 'NetworkManager to reconnect WireGuard while the GUI remained closed.\n'
  printf '\nLaunch PIA Bazzite again from your Favorites now.\n'
  exit 0
fi

printf '\nAPPLICATION-CRASH TEST FAILED\n'
printf 'The temporary nftables table has been removed during cleanup.\n'
printf 'Launch PIA Bazzite again from your Favorites after checking connectivity.\n'
exit 1
