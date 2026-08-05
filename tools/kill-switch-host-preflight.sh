#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$ROOT/pia-kill-switch-host-preflight-v2.txt}"

exec > >(tee "$REPORT") 2>&1

PASSED=0
WARNINGS=0
FAILURES=0

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

have() {
  command -v "$1" >/dev/null 2>&1
}

mask_ipv4() {
  local value="$1"
  awk -F. 'NF == 4 { printf "%s.%s.x.x", $1, $2; exit }' <<<"$value"
}

mask_ipv6() {
  local value="$1"
  printf '%s::…' "${value%%:*}"
}

printf 'PIA Bazzite guarded host-test preflight v2\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This check is read-only. It does not change nftables or NetworkManager.\n\n'

printf '%s\n' '--- Required commands ---'
for tool in nmcli wg ip nft systemctl systemd-run python3 sudo; do
  if have "$tool"; then
    pass "$tool found at $(command -v "$tool")"
  else
    fail "$tool was not found"
  fi
done
printf '\n'

printf '%s\n' '--- Read-only administrator access ---'
printf '%s\n' \
  'WireGuard status is protected on this system.' \
  'sudo is used only for read-only wg/nft queries.'
if sudo -v; then
  pass "temporary sudo authorization is available"
else
  fail "sudo authorization failed"
fi
printf '\n'

printf '%s\n' '--- Active PIA connection ---'
ACTIVE_LINE="$(
  nmcli -t -f NAME,TYPE,DEVICE connection show --active 2>/dev/null \
    | grep -F 'PIA Bazzite:wireguard:' \
    | head -n 1 \
    || true
)"

if [[ -n "$ACTIVE_LINE" ]]; then
  ACTIVE_DEVICE="${ACTIVE_LINE##*:}"
  pass "PIA Bazzite WireGuard profile is active"
  printf 'Interface reported by NetworkManager: %s\n' "$ACTIVE_DEVICE"
else
  ACTIVE_DEVICE=""
  fail "PIA Bazzite is not connected"
fi

if ip link show piabazzite >/dev/null 2>&1; then
  pass "WireGuard interface piabazzite exists"
else
  fail "WireGuard interface piabazzite does not exist"
fi

if [[ -n "$ACTIVE_DEVICE" && "$ACTIVE_DEVICE" != "piabazzite" ]]; then
  warn "NetworkManager reports an unexpected interface: $ACTIVE_DEVICE"
fi
printf '\n'

printf '%s\n' '--- Real WireGuard endpoint ---'
WG_ERROR="$(mktemp)"
trap 'rm -f "$WG_ERROR"' EXIT

ENDPOINT_RAW="$(
  sudo wg show piabazzite endpoints 2>"$WG_ERROR" \
    | awk 'NF >= 2 { print $2; exit }'
)"
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""

if [[ "$ENDPOINT_RAW" =~ ^\[([0-9A-Fa-f:]+)\]:([0-9]+)$ ]]; then
  ENDPOINT_IP="${BASH_REMATCH[1]}"
  ENDPOINT_PORT="${BASH_REMATCH[2]}"
  ENDPOINT_FAMILY="IPv6"
elif [[ "$ENDPOINT_RAW" =~ ^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):([0-9]+)$ ]]; then
  ENDPOINT_IP="${BASH_REMATCH[1]}"
  ENDPOINT_PORT="${BASH_REMATCH[2]}"
  ENDPOINT_FAMILY="IPv4"
fi

if [[ -n "$ENDPOINT_IP" && -n "$ENDPOINT_PORT" ]]; then
  pass "a numeric WireGuard endpoint was detected"
  if [[ "$ENDPOINT_FAMILY" == "IPv4" ]]; then
    printf 'Endpoint: %s:%s (%s, masked)\n' \
      "$(mask_ipv4 "$ENDPOINT_IP")" "$ENDPOINT_PORT" "$ENDPOINT_FAMILY"
  else
    printf 'Endpoint: [%s]:%s (%s, masked)\n' \
      "$(mask_ipv6 "$ENDPOINT_IP")" "$ENDPOINT_PORT" "$ENDPOINT_FAMILY"
  fi
else
  fail "the active WireGuard endpoint could not be parsed"
  printf 'Raw endpoint field: %s\n' "${ENDPOINT_RAW:-empty}"
  if [[ -s "$WG_ERROR" ]]; then
    printf 'wg error: %s\n' "$(tr '\n' ' ' < "$WG_ERROR")"
  fi
fi

FWMARK="$(sudo wg show piabazzite fwmark 2>/dev/null | head -n 1 || true)"
if [[ -n "$FWMARK" && "$FWMARK" != "off" ]]; then
  pass "WireGuard fwmark is available"
  printf 'WireGuard fwmark: %s\n' "$FWMARK"
else
  warn "WireGuard fwmark is off or unavailable"
fi

LATEST_HANDSHAKE="$(
  sudo wg show piabazzite latest-handshakes 2>/dev/null \
    | awk 'NF >= 2 { print $2; exit }'
)"
if [[ "$LATEST_HANDSHAKE" =~ ^[0-9]+$ ]] && (( LATEST_HANDSHAKE > 0 )); then
  NOW="$(date +%s)"
  AGE=$((NOW - LATEST_HANDSHAKE))
  if (( AGE <= 300 )); then
    pass "the latest WireGuard handshake is recent (${AGE}s ago)"
  else
    warn "the latest WireGuard handshake is ${AGE}s old"
  fi
else
  warn "no successful WireGuard handshake timestamp was found"
fi
printf '\n'

printf '%s\n' '--- Endpoint route outside the tunnel ---'
if [[ -n "$ENDPOINT_IP" ]]; then
  if [[ -n "$FWMARK" && "$FWMARK" != "off" ]]; then
    ROUTE_LINE="$(
      ip route get "$ENDPOINT_IP" mark "$FWMARK" 2>/dev/null \
        | head -n 1 \
        || true
    )"
  else
    ROUTE_LINE="$(
      ip route get "$ENDPOINT_IP" 2>/dev/null \
        | head -n 1 \
        || true
    )"
  fi

  if [[ -n "$ROUTE_LINE" ]]; then
    printf 'Endpoint route: %s\n' "$ROUTE_LINE"
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

    if [[ -n "$ROUTE_DEVICE" && "$ROUTE_DEVICE" != "piabazzite" ]]; then
      pass "the WireGuard endpoint has a physical escape route via $ROUTE_DEVICE"
    elif [[ "$ROUTE_DEVICE" == "piabazzite" ]]; then
      fail "the endpoint route unexpectedly points back into piabazzite"
    else
      fail "the endpoint route device could not be determined"
    fi
  else
    fail "no route to the WireGuard endpoint could be determined"
  fi
else
  fail "endpoint-route check skipped because the endpoint is unknown"
fi
printf '\n'

printf '%s\n' '--- Current default routes ---'
IPV4_DEFAULTS="$(ip -4 route show default 2>/dev/null || true)"
IPV6_DEFAULTS="$(ip -6 route show default 2>/dev/null || true)"

if [[ -n "$IPV4_DEFAULTS" ]]; then
  printf 'IPv4:\n%s\n' "$(sed 's/^/  /' <<<"$IPV4_DEFAULTS")"
  pass "at least one IPv4 default route exists"
else
  warn "no IPv4 default route was shown"
fi

if [[ -n "$IPV6_DEFAULTS" ]]; then
  printf 'IPv6:\n%s\n' "$(sed 's/^/  /' <<<"$IPV6_DEFAULTS")"
else
  printf 'IPv6: none shown\n'
fi

if ip -6 route show type blackhole default 2>/dev/null \
    | grep -q 'blackhole default'; then
  pass "PIA Bazzite IPv6 blackhole protection is active"
else
  warn "the expected IPv6 blackhole route was not found"
fi
printf '\n'

printf '%s\n' '--- Firewall coexistence ---'
if systemctl is-active --quiet firewalld 2>/dev/null; then
  printf 'firewalld: active\n'
  warn "firewalld is active; the guarded test must verify coexistence"
else
  printf 'firewalld: inactive or not installed\n'
  pass "no active firewalld service was detected"
fi

if sudo nft list table inet pia_bazzite_killswitch_test \
    >/dev/null 2>&1; then
  warn "a previous pia_bazzite_killswitch_test table already exists"
else
  pass "no previous pia_bazzite_killswitch_test table exists"
fi
printf '\n'

printf '%s\n' '--- Automatic safety reset capability ---'
if [[ "$(ps -p 1 -o comm= 2>/dev/null | tr -d ' ')" == "systemd" ]]; then
  pass "systemd is PID 1"
else
  fail "systemd is not PID 1"
fi

if systemd-run --help 2>&1 | grep -q -- '--on-active'; then
  pass "systemd-run supports a timed --on-active unit"
else
  fail "systemd-run does not advertise --on-active support"
fi

if systemctl --version >/dev/null 2>&1; then
  pass "systemctl can communicate with systemd"
else
  fail "systemctl is unavailable"
fi

printf '\n%s\n' '--- Result ---'
printf 'Passed: %d\n' "$PASSED"
printf 'Warnings: %d\n' "$WARNINGS"
printf 'Failures: %d\n' "$FAILURES"

if (( FAILURES == 0 )); then
  printf '\nREADY FOR REVIEW: send this report before running the guarded host test.\n'
  exit 0
fi

printf '\nNOT READY: do not run a real host test yet.\n'
exit 1
