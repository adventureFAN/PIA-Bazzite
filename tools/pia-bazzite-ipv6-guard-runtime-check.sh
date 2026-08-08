#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-}"
if [[ "$MODE" != "connected" && "$MODE" != "disconnected" ]]; then
  printf 'Usage: %s connected|disconnected\n' "$0" >&2
  exit 2
fi

if command -v xdg-user-dir >/dev/null 2>&1; then
  DOWNLOAD_DIR="$(xdg-user-dir DOWNLOAD 2>/dev/null || true)"
else
  DOWNLOAD_DIR=""
fi
[[ -n "$DOWNLOAD_DIR" ]] || DOWNLOAD_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOAD_DIR"
REPORT="$DOWNLOAD_DIR/PIA-Bazzite-stage8C3A7-ipv6-guard-${MODE}.txt"

PASS=0
FAIL=0
pass() { printf 'PASS: %s\n' "$*"; PASS=$((PASS + 1)); }
fail() { printf 'FAIL: %s\n' "$*"; FAIL=$((FAIL + 1)); }

active_pia() {
  nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep -Fxq 'PIA Bazzite:wireguard'
}

numeric_tcp() {
  local family="$1" host="$2" port="$3"
  python3 - "$family" "$host" "$port" <<'PY'
import socket, sys
family = socket.AF_INET if sys.argv[1] == "4" else socket.AF_INET6
sock = socket.socket(family, socket.SOCK_STREAM)
sock.settimeout(5.0)
try:
    sock.connect((sys.argv[2], int(sys.argv[3])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

guard_json() {
  sudo -n nft -j list table inet pia_bazzite_ipv6_guard 2>/dev/null
}

guard_counter() {
  python3 -c '
import json, sys
raw=json.load(sys.stdin)
for item in raw.get("nftables", []):
    rule=item.get("rule") if isinstance(item, dict) else None
    if not isinstance(rule, dict) or rule.get("comment") != "pia-bazzite:ipv6-guard:v1:block-ipv6":
        continue
    for expr in rule.get("expr", []):
        if isinstance(expr, dict) and isinstance(expr.get("counter"), dict):
            print(int(expr["counter"].get("packets", 0)))
            raise SystemExit(0)
raise SystemExit(1)
'
}

validate_guard_shape() {
  PYTHONPATH="$ROOT" python3 -c '
import sys
from helper.pia_bazzite_kill_switch_helper.core import parse_ipv6_guard_status_json
text=sys.stdin.read()
status=parse_ipv6_guard_status_json(text)
if not status.get("verified") or status.get("state") != "active" or not status.get("present"):
    print(status.get("problems", []), file=sys.stderr)
    raise SystemExit(1)
' 
}

{
  echo "PIA Bazzite Stage-8C.3A7 normal-VPN IPv6 guard runtime check"
  echo "Mode: $MODE"
  date --iso-8601=seconds 2>/dev/null || date
  echo "This check uses sudo only for read-only nftables inspection. It never changes VPN, NetworkManager, helper, or firewall state."
  echo

  for tool in nmcli ip nft python3 sudo; do
    if command -v "$tool" >/dev/null 2>&1; then pass "$tool is available"; else fail "$tool is missing"; fi
  done

  if sudo -n true 2>/dev/null; then
    pass "sudo authorization is already available for read-only firewall inspection"
  else
    echo "Requesting sudo authorization for read-only nftables inspection..."
    if sudo -v; then pass "sudo authorization is available"; else fail "sudo authorization failed"; fi
  fi

  if [[ "$MODE" == "connected" ]]; then
    echo
    echo "--- Connected normal-VPN state ---"
    if active_pia; then pass "PIA Bazzite WireGuard profile is active"; else fail "PIA Bazzite WireGuard profile is not active"; fi

    route4="$(ip -4 route get 1.1.1.1 2>/dev/null || true)"
    route4_redacted="$(sed -E 's/( src )[0-9.]+/\1<redacted>/g' <<<"$route4")"
    printf 'IPv4 route: %s\n' "$route4_redacted"
    if grep -Eq '(^| )dev piabazzite( |$)' <<<"$route4"; then pass "public IPv4 selects piabazzite"; else fail "public IPv4 does not select piabazzite"; fi

    if sudo -n nft list table inet pia_bazzite_killswitch >/dev/null 2>&1; then
      fail "full Session Kill Switch table is present during the normal-VPN guard test"
    else
      pass "full Session Kill Switch table is absent"
    fi

    before_json="$(guard_json || true)"
    if [[ -n "$before_json" ]] && validate_guard_shape <<<"$before_json"; then
      pass "IPv6-only guard table has the exact verified production shape"
    else
      fail "IPv6-only guard table is missing or structurally invalid"
    fi
    before_counter="$(guard_counter <<<"$before_json" 2>/dev/null || echo -1)"
    printf 'IPv6 block counter before probe: %s\n' "$before_counter"

    if numeric_tcp 4 1.1.1.1 443; then pass "numeric public IPv4 TCP works through the normal VPN"; else fail "numeric public IPv4 TCP failed"; fi
    if numeric_tcp 6 2606:4700:4700::1111 443; then
      fail "numeric public IPv6 TCP escaped while the IPv6-only guard should be active"
    else
      pass "numeric public IPv6 TCP is blocked"
    fi

    after_json="$(guard_json || true)"
    after_counter="$(guard_counter <<<"$after_json" 2>/dev/null || echo -1)"
    printf 'IPv6 block counter after probe: %s\n' "$after_counter"
    if [[ "$before_counter" =~ ^[0-9]+$ && "$after_counter" =~ ^[0-9]+$ ]] && (( after_counter > before_counter )); then
      pass "the exact IPv6 guard block-rule counter increased"
    else
      fail "the IPv6 guard counter did not prove that the blocked probe hit the rule"
    fi

    country="$(curl -4 -fsS --max-time 8 https://api.country.is/ 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("country","UNKNOWN"))' 2>/dev/null || true)"
    printf 'IPv4 egress country (no IP): %s\n' "${country:-UNAVAILABLE}"
  else
    echo
    echo "--- Intentional disconnected state ---"
    if active_pia; then fail "PIA Bazzite WireGuard profile is still active"; else pass "PIA Bazzite WireGuard profile is inactive"; fi
    if sudo -n nft list table inet pia_bazzite_ipv6_guard >/dev/null 2>&1; then fail "IPv6-only guard table still exists after disconnect"; else pass "IPv6-only guard table is absent"; fi
    if sudo -n nft list table inet pia_bazzite_killswitch >/dev/null 2>&1; then fail "full Session Kill Switch table is unexpectedly present"; else pass "full Session Kill Switch table is absent"; fi
    if numeric_tcp 4 1.1.1.1 443; then pass "normal public IPv4 TCP works after disconnect"; else fail "normal public IPv4 TCP failed after disconnect"; fi
    if numeric_tcp 6 2606:4700:4700::1111 443; then pass "normal public IPv6 TCP works again after disconnect"; else fail "normal public IPv6 TCP did not recover after disconnect"; fi
  fi

  echo
  echo "--- Result ---"
  printf 'PASS count: %d\n' "$PASS"
  printf 'FAIL count: %d\n' "$FAIL"
  echo "Report: $REPORT"
  if (( FAIL == 0 )); then
    echo "ALL STAGE-8C.3A7 IPV6 GUARD RUNTIME CHECKS PASSED ($MODE)"
  else
    echo "STAGE-8C.3A7 IPV6 GUARD RUNTIME CHECK FAILED ($MODE)"
  fi
} | tee "$REPORT"

if (( FAIL != 0 )); then
  exit 1
fi
