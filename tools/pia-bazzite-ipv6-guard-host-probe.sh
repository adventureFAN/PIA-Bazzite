#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-${HOME}/Downloads/PIA-Bazzite-ipv6-guard-host-probe.txt}"
TABLE="pia_bazzite_ipv6_guard_probe"
CHAIN="output"
PRODUCTION_TABLE="pia_bazzite_killswitch"
RESET_UNIT="pia-bazzite-ipv6-guard-probe-reset"
RESET_SECONDS=120
IPV4_TARGET="1.1.1.1"
IPV6_TARGET="2606:4700:4700::1111"
TEST_PORT=443

PASSED=0
FAILURES=0
WARNINGS=0
GUARD_ACTIVE=0
RESET_SCHEDULED=0
CLEANUP_RUNNING=0
NFT_BIN="$(command -v nft || true)"
TMP_RULESET="$(mktemp /tmp/pia-bazzite-ipv6-guard-probe.XXXXXX.nft)"

mkdir -p "$(dirname "$REPORT")"
exec > >(tee "$REPORT") 2>&1

pass() {
  printf 'PASS: %s\n' "$1"
  PASSED=$((PASSED + 1))
}

fail() {
  printf 'FAIL: %s\n' "$1"
  FAILURES=$((FAILURES + 1))
}

warn() {
  printf 'WARN: %s\n' "$1"
  WARNINGS=$((WARNINGS + 1))
}

cancel_reset_timer() {
  if (( RESET_SCHEDULED == 1 )); then
    sudo systemctl stop \
      "${RESET_UNIT}.timer" \
      "${RESET_UNIT}.service" \
      >/dev/null 2>&1 || true
    sudo systemctl reset-failed \
      "${RESET_UNIT}.service" \
      >/dev/null 2>&1 || true
    RESET_SCHEDULED=0
  fi
}

remove_probe_table() {
  if [[ -n "$NFT_BIN" ]] && sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
    sudo "$NFT_BIN" delete table inet "$TABLE" >/dev/null 2>&1 || true
  fi
  GUARD_ACTIVE=0
}

cleanup() {
  local exit_code=$?

  if (( CLEANUP_RUNNING == 1 )); then
    return
  fi
  CLEANUP_RUNNING=1

  set +e
  remove_probe_table
  cancel_reset_timer
  rm -f "$TMP_RULESET"

  if (( exit_code != 0 )); then
    printf '\nCleanup attempted after an early exit.\n'
    printf 'Emergency command if IPv6 remains blocked:\n'
    printf '  sudo nft delete table inet %s\n' "$TABLE"
  fi
}
trap cleanup EXIT INT TERM

tcp_probe() {
  local family="$1"
  local address="$2"
  local port="$3"
  local timeout_seconds="${4:-4}"

  python3 - "$family" "$address" "$port" "$timeout_seconds" <<'PY'
from __future__ import annotations

import socket
import sys

family_text, address, port_text, timeout_text = sys.argv[1:5]
family = socket.AF_INET6 if family_text == "6" else socket.AF_INET
sockaddr = (address, int(port_text), 0, 0) if family == socket.AF_INET6 else (address, int(port_text))

with socket.socket(family, socket.SOCK_STREAM) as sock:
    sock.settimeout(float(timeout_text))
    sock.connect(sockaddr)
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

wait_for_success() {
  local attempts="$1"
  shift
  local attempt
  for attempt in $(seq 1 "$attempts"); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

block_rule_packets() {
  sudo "$NFT_BIN" list chain inet "$TABLE" "$CHAIN" 2>/dev/null \
    | awk '
        index($0, "comment \"pia-bazzite:ipv6-guard-probe:block\"") {
          for (i = 1; i <= NF; i++) {
            if ($i == "packets" && i < NF) {
              print $(i + 1)
              exit
            }
          }
        }
      '
}

printf 'PIA Bazzite isolated IPv6-only nftables guard host probe\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf '\n'
printf '%s\n' \
  'Purpose: prove the firewall mechanism before changing production code.' \
  'This probe does NOT connect PIA, install/update the helper, or modify project files.' \
  'It creates one temporary nftables table that blocks only outbound IPv6.' \
  'IPv4 must continue to work throughout the guard.' \
  '' \
  "A root-owned automatic reset deletes the probe table after ${RESET_SECONDS} seconds." \
  'Normal cleanup deletes it sooner.' \
  '' \
  'Emergency command in another terminal:' \
  "  sudo nft delete table inet ${TABLE}" \
  '' \
  'PIA Bazzite should be CLOSED and the production Kill Switch must be inactive.'

read -r -p 'Type TEST exactly to continue: ' CONFIRM
if [[ "$CONFIRM" != "TEST" ]]; then
  printf 'Cancelled. Nothing was changed.\n'
  exit 0
fi

printf '\n--- Preflight ---\n'
for tool in nft python3 sudo systemctl systemd-run nmcli ip; do
  if command -v "$tool" >/dev/null 2>&1; then
    pass "$tool is available"
  else
    fail "$tool is missing"
  fi
done

if (( FAILURES > 0 )); then
  printf 'Required commands are missing. No firewall table was created.\n'
  exit 1
fi

if ! sudo -v; then
  fail "sudo authorization was not obtained"
  exit 1
fi
pass "sudo authorization is available for the temporary probe"

if sudo "$NFT_BIN" list table inet "$PRODUCTION_TABLE" >/dev/null 2>&1; then
  fail "production Kill Switch table is active; run Emergency Reset first"
  exit 1
fi
pass "production Kill Switch firewall table is absent"

if nmcli -t -f TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: '$1 == "wireguard" && $2 == "piabazzite" { found=1 } END { exit found ? 0 : 1 }'; then
  fail "PIA Bazzite WireGuard is active; disconnect it before this isolated probe"
  exit 1
fi
pass "PIA Bazzite WireGuard is inactive"

remove_probe_table

printf '\n--- Baseline before the guard ---\n'
expect_success \
  "numeric public IPv4 TCP connectivity works before the probe" \
  tcp_probe 4 "$IPV4_TARGET" "$TEST_PORT" 5 || exit 1
expect_success \
  "numeric public IPv6 TCP connectivity works before the probe" \
  tcp_probe 6 "$IPV6_TARGET" "$TEST_PORT" 5 || exit 1

BASE_ROUTE6="$(ip -6 route get "$IPV6_TARGET" 2>/dev/null || true)"
BASE_DEV6="$(awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' <<<"$BASE_ROUTE6")"
printf 'Baseline IPv6 route device: %s\n' "${BASE_DEV6:-UNAVAILABLE}"
if [[ -n "$BASE_DEV6" && "$BASE_DEV6" != "piabazzite" ]]; then
  pass "baseline public IPv6 uses a non-PIA path, so the probe can test the real leak path"
else
  fail "baseline public IPv6 route is unavailable or unexpectedly uses piabazzite"
  exit 1
fi

printf '\n--- Arm independent automatic cleanup ---\n'
sudo systemctl stop \
  "${RESET_UNIT}.timer" \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true
sudo systemctl reset-failed \
  "${RESET_UNIT}.service" \
  >/dev/null 2>&1 || true

if sudo systemd-run \
    --quiet \
    --unit="$RESET_UNIT" \
    --on-active="${RESET_SECONDS}s" \
    "$NFT_BIN" delete table inet "$TABLE"; then
  RESET_SCHEDULED=1
  pass "automatic IPv6-guard probe cleanup is armed for ${RESET_SECONDS} seconds"
else
  fail "automatic cleanup timer could not be created"
  exit 1
fi

if ! sudo systemctl is-active --quiet "${RESET_UNIT}.timer"; then
  fail "automatic cleanup timer is not active"
  exit 1
fi

printf '\n--- Install isolated IPv6-only guard ---\n'
cat >"$TMP_RULESET" <<NFT
add table inet $TABLE
add chain inet $TABLE $CHAIN { type filter hook output priority -110; policy accept; }
add rule inet $TABLE $CHAIN oifname "lo" counter accept comment "pia-bazzite:ipv6-guard-probe:loopback"
add rule inet $TABLE $CHAIN meta nfproto ipv6 counter reject with icmpx type admin-prohibited comment "pia-bazzite:ipv6-guard-probe:block"
NFT

if sudo "$NFT_BIN" --check -f "$TMP_RULESET"; then
  pass "nftables accepts the isolated IPv6-only ruleset"
else
  fail "nftables rejected the isolated IPv6-only ruleset"
  exit 1
fi

if sudo "$NFT_BIN" -f "$TMP_RULESET"; then
  GUARD_ACTIVE=1
  pass "temporary IPv6-only firewall guard is active"
else
  fail "temporary IPv6-only firewall guard could not be installed"
  exit 1
fi

if sudo "$NFT_BIN" list chain inet "$TABLE" "$CHAIN" 2>/dev/null \
    | grep -Fq 'pia-bazzite:ipv6-guard-probe:block'; then
  pass "the exact IPv6 block rule is present"
else
  fail "the expected IPv6 block rule is missing"
  exit 1
fi

printf '\n--- Prove family isolation while guard is active ---\n'
expect_success \
  "public IPv4 TCP remains usable while the IPv6-only guard is active" \
  tcp_probe 4 "$IPV4_TARGET" "$TEST_PORT" 5

PACKETS_BEFORE="$(block_rule_packets)"
[[ "$PACKETS_BEFORE" =~ ^[0-9]+$ ]] || PACKETS_BEFORE=0

expect_blocked \
  "public IPv6 TCP is blocked by the guard" \
  tcp_probe 6 "$IPV6_TARGET" "$TEST_PORT" 4

PACKETS_AFTER="$(block_rule_packets)"
[[ "$PACKETS_AFTER" =~ ^[0-9]+$ ]] || PACKETS_AFTER=0
if (( PACKETS_AFTER > PACKETS_BEFORE )); then
  pass "IPv6 block-rule packet counter increased during the blocked probe"
else
  fail "IPv6 block-rule packet counter did not increase"
fi

GUARDED_ROUTE6="$(ip -6 route get "$IPV6_TARGET" 2>/dev/null || true)"
GUARDED_DEV6="$(awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' <<<"$GUARDED_ROUTE6")"
printf 'IPv6 route device while firewall guard is active: %s\n' "${GUARDED_DEV6:-UNAVAILABLE}"
if [[ "$GUARDED_DEV6" == "$BASE_DEV6" ]]; then
  pass "the guard blocks IPv6 without depending on a NetworkManager route change"
else
  warn "the IPv6 route device changed during the probe; firewall blocking was still tested independently"
fi

if (( FAILURES > 0 )); then
  printf '\nThe isolation proof failed; removing the temporary guard now.\n'
  remove_probe_table
  cancel_reset_timer
  exit 1
fi

printf '\n--- Remove guard and prove restoration ---\n'
remove_probe_table
if sudo "$NFT_BIN" list table inet "$TABLE" >/dev/null 2>&1; then
  fail "temporary IPv6-only table still exists after removal"
else
  pass "temporary IPv6-only table is absent after removal"
fi

if wait_for_success 10 tcp_probe 4 "$IPV4_TARGET" "$TEST_PORT" 4; then
  pass "public IPv4 still works after guard removal"
else
  fail "public IPv4 did not recover after guard removal"
fi

if wait_for_success 10 tcp_probe 6 "$IPV6_TARGET" "$TEST_PORT" 4; then
  pass "public IPv6 works again after guard removal"
else
  fail "public IPv6 did not recover after guard removal"
fi

cancel_reset_timer
if sudo systemctl is-active --quiet "${RESET_UNIT}.timer" 2>/dev/null; then
  fail "automatic cleanup timer is still active"
else
  pass "automatic cleanup timer was cancelled after verified restoration"
fi

printf '\n--- Result ---\n'
printf 'PASS count: %d\n' "$PASSED"
printf 'WARN count: %d\n' "$WARNINGS"
printf 'FAIL count: %d\n' "$FAILURES"
printf 'Report: %s\n' "$REPORT"

if (( FAILURES == 0 )); then
  printf '\nALL IPV6-ONLY FIREWALL GUARD HOST PROBE CHECKS PASSED\n'
  printf 'No PIA VPN profile, production Kill Switch table, helper installation, or project file was modified.\n'
  exit 0
fi

printf '\nIPV6-ONLY FIREWALL GUARD HOST PROBE FAILED\n'
exit 1
