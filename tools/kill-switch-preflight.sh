#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$ROOT/pia-kill-switch-preflight.txt}"

exec > >(tee "$REPORT") 2>&1

ok=0
warnings=0
missing=0

pass() {
  printf 'PASS  %s\n' "$1"
  ok=$((ok + 1))
}

warn() {
  printf 'WARN  %s\n' "$1"
  warnings=$((warnings + 1))
}

fail() {
  printf 'FAIL  %s\n' "$1"
  missing=$((missing + 1))
}

have() {
  command -v "$1" >/dev/null 2>&1
}

printf 'PIA Bazzite session kill-switch preflight\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This check does not change networking or firewall rules.\n\n'

printf '%s\n' '--- Platform ---'
printf 'Kernel: %s\n' "$(uname -r)"
printf 'Architecture: %s\n' "$(uname -m)"
printf 'Session: %s\n' "${XDG_SESSION_TYPE:-unknown}"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  printf 'Operating system: %s\n' "${PRETTY_NAME:-unknown}"
fi
printf '\n'

printf '%s\n' '--- Required tools ---'
for tool in ip nft nmcli wg ping python3; do
  if have "$tool"; then
    pass "$tool found at $(command -v "$tool")"
  else
    fail "$tool was not found"
  fi
done

if have sudo; then
  pass "sudo is available"
elif have pkexec; then
  pass "pkexec is available"
else
  fail "neither sudo nor pkexec is available"
fi
printf '\n'

printf '%s\n' '--- Versions ---'
have ip && ip -Version 2>&1 | head -n 1 || true
have nft && nft --version 2>&1 | head -n 1 || true
have nmcli && nmcli --version 2>&1 | head -n 1 || true
have wg && wg --version 2>&1 | head -n 1 || true
have python3 && python3 --version 2>&1 | head -n 1 || true
printf '\n'

printf '%s\n' '--- NetworkManager ---'
if have nmcli; then
  nm_state="$(nmcli -t -f STATE general 2>/dev/null || true)"
  if [[ -n "$nm_state" ]]; then
    pass "NetworkManager answered: $nm_state"
  else
    fail "NetworkManager did not answer"
  fi

  printf 'Active connection names and types:\n'
  nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
    | sed 's/^/  /' \
    || true

  if nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
      | grep -Fxq 'PIA Bazzite:wireguard'; then
    pass "PIA Bazzite WireGuard profile is active"
  else
    warn "PIA Bazzite WireGuard profile is not active (fine for this preflight)"
  fi
fi
printf '\n'

printf '%s\n' '--- Routing summary ---'
if have ip; then
  ipv4_devices="$(ip -4 route show default 2>/dev/null | awk '{print $5}' | sort -u | paste -sd, -)"
  ipv6_devices="$(ip -6 route show default 2>/dev/null | awk '{print $5}' | sort -u | paste -sd, -)"
  printf 'IPv4 default-route device(s): %s\n' "${ipv4_devices:-none}"
  printf 'IPv6 default-route device(s): %s\n' "${ipv6_devices:-none}"

  if ip link show piabazzite >/dev/null 2>&1; then
    pass "piabazzite interface exists"
  else
    warn "piabazzite interface does not currently exist"
  fi
fi
printf '\n'

printf '%s\n' '--- Firewall environment ---'
if have systemctl && systemctl is-active --quiet firewalld 2>/dev/null; then
  printf 'firewalld: active\n'
else
  printf 'firewalld: not active or not installed\n'
fi

if have nft; then
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    printf 'Current host nftables tables:\n'
    nft list tables 2>/dev/null | sed 's/^/  /' || true
  else
    printf 'Current host nftables tables: not read (preflight was not run as root)\n'
  fi
fi
printf '\n'

printf '%s\n' '--- Namespace capability ---'
if have ip && ip netns list >/dev/null 2>&1; then
  pass "network namespace commands are available"
else
  fail "network namespace commands are unavailable"
fi
printf '\n'

printf '%s\n' '--- Result ---'
printf 'Passed: %d\n' "$ok"
printf 'Warnings: %d\n' "$warnings"
printf 'Failures: %d\n' "$missing"

if (( missing == 0 )); then
  printf '\nREADY: the isolated namespace test can be attempted.\n'
  exit 0
fi

printf '\nNOT READY: one or more required tools are missing.\n'
exit 1
