#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-$ROOT/pia-kill-switch-automatic-reset-test.txt}"
TABLE="pia_bazzite_killswitch_automatic_reset_test"
UNIT="pia-bazzite-killswitch-automatic-reset-test"
VPN_IF="piabazzite"
RESET_SECONDS=35
PASS=0
WARN=0
FAIL=0
VPN_UUID=""
ENDPOINT_IP=""
ENDPOINT_PORT=""
ENDPOINT_FAMILY=""
ROUTE_DEVICE=""
TABLE_CREATED=0
TIMER_CREATED=0
CLEANING=0
TMP_RULES="$(mktemp /tmp/pia-bazzite-auto-reset.XXXXXX.nft)"

exec > >(tee "$REPORT") 2>&1

ok(){ printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
warn(){ printf 'WARN  %s\n' "$1"; WARN=$((WARN+1)); }
bad(){ printf 'FAIL  %s\n' "$1"; FAIL=$((FAIL+1)); }

vpn_active(){
  nmcli -t -f UUID,TYPE,DEVICE connection show --active 2>/dev/null \
    | awk -F: '$2=="wireguard" && $3=="piabazzite"{found=1} END{exit found?0:1}' \
    && ip link show "$VPN_IF" >/dev/null 2>&1
}

handshake(){
  sudo -n wg show "$VPN_IF" latest-handshakes 2>/dev/null \
    | awk 'NF>=2{print $2; exit}'
}

tcp_probe(){
  python3 - "$1" "$2" "$3" "${4:-5}" <<'PY2'
import socket,sys
fam=socket.AF_INET6 if sys.argv[1]=='6' else socket.AF_INET
with socket.socket(fam,socket.SOCK_STREAM) as s:
    s.settimeout(float(sys.argv[4]))
    s.connect((sys.argv[2],int(sys.argv[3])))
PY2
}

block_packets(){
  sudo -n nft list chain inet "$TABLE" output 2>/dev/null \
    | awk '/comment "block outside VPN"/{for(i=1;i<=NF;i++)if($i=="packets"){print $(i+1);exit}}'
}

remove_table(){
  if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
    sudo -n nft delete table inet "$TABLE" >/dev/null 2>&1 || true
  fi
  TABLE_CREATED=0
}

cancel_timer(){
  sudo -n systemctl stop "${UNIT}.timer" "${UNIT}.service" >/dev/null 2>&1 || true
  sudo -n systemctl reset-failed "${UNIT}.service" >/dev/null 2>&1 || true
  TIMER_CREATED=0
}

restore_vpn(){
  if [[ -n "$VPN_UUID" ]] && ! vpn_active; then
    timeout 90s nmcli connection up uuid "$VPN_UUID" >/dev/null 2>&1 || true
  fi
}

cleanup(){
  local rc=$?
  (( CLEANING==1 )) && return
  CLEANING=1
  set +e
  remove_table
  cancel_timer
  restore_vpn
  rm -f "$TMP_RULES"
  if (( rc!=0 )); then
    printf '\nThe automatic-reset test exited early.\n'
    printf 'The temporary table and timer were removed; PIA was restored where possible.\n'
  fi
}
trap cleanup EXIT INT TERM

printf 'PIA Bazzite automatic kill-switch safety-reset test\n'
printf 'Generated: %s\n\n' "$(date --iso-8601=seconds)"
printf '%s\n' \
  'This test blocks the current PIA endpoint and disconnects WireGuard.' \
  'IPv4 and IPv6 must remain blocked.' \
  '' \
  "After ${RESET_SECONDS} seconds, an independent root-owned systemd timer must" \
  'remove the temporary nftables table and reactivate the saved PIA profile.' \
  '' \
  'Do not change Wi-Fi, Ethernet, or PIA manually during the test.' \
  'The complete test normally takes about one minute.'

read -r -p 'Type RESET exactly to continue: ' CONFIRM
[[ "$CONFIRM" == "RESET" ]] || { echo 'Cancelled. Nothing was changed.'; exit 0; }

printf '\n--- Preflight ---\n'
for tool in nmcli wg ip nft systemctl systemd-run python3 sudo timeout bash; do
  command -v "$tool" >/dev/null 2>&1 && ok "$tool is available" || bad "$tool is missing"
done
(( FAIL==0 )) || exit 1
sudo -v || { bad 'sudo authorization failed'; exit 1; }
ok 'temporary sudo authorization is available'

VPN_LINE="$(nmcli -t -f UUID,NAME,TYPE,DEVICE connection show --active 2>/dev/null | awk -F: '$3=="wireguard" && $4=="piabazzite"{print;exit}')"
[[ -n "$VPN_LINE" ]] || { bad 'PIA Bazzite is not connected'; exit 1; }
IFS=: read -r VPN_UUID VPN_NAME VPN_TYPE VPN_DEVICE <<<"$VPN_LINE"
ok 'PIA Bazzite WireGuard profile is active'
printf 'VPN profile: %s\n' "$VPN_NAME"

ENDPOINT="$(sudo -n wg show "$VPN_IF" endpoints 2>/dev/null | awk 'NF>=2{print $2;exit}')"
if [[ "$ENDPOINT" =~ ^\[([0-9A-Fa-f:]+)\]:([0-9]+)$ ]]; then
  ENDPOINT_IP="${BASH_REMATCH[1]}"; ENDPOINT_PORT="${BASH_REMATCH[2]}"; ENDPOINT_FAMILY=IPv6
elif [[ "$ENDPOINT" =~ ^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):([0-9]+)$ ]]; then
  ENDPOINT_IP="${BASH_REMATCH[1]}"; ENDPOINT_PORT="${BASH_REMATCH[2]}"; ENDPOINT_FAMILY=IPv4
else
  bad 'the current numeric WireGuard endpoint could not be parsed'; exit 1
fi
ok 'the current numeric WireGuard endpoint was detected'

FWMARK="$(sudo -n wg show "$VPN_IF" fwmark 2>/dev/null | head -n1)"
[[ -n "$FWMARK" && "$FWMARK" != off ]] || { bad 'the WireGuard fwmark is unavailable'; exit 1; }
ok 'the WireGuard fwmark is available'

if [[ "$ENDPOINT_FAMILY" == IPv4 ]]; then
  ROUTE="$(ip -4 route get "$ENDPOINT_IP" mark "$FWMARK" 2>/dev/null | head -n1)"
else
  ROUTE="$(ip -6 route get "$ENDPOINT_IP" mark "$FWMARK" 2>/dev/null | head -n1)"
fi
ROUTE_DEVICE="$(awk '{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}' <<<"$ROUTE")"
[[ -n "$ROUTE_DEVICE" && "$ROUTE_DEVICE" != "$VPN_IF" ]] || { bad 'the physical endpoint route is unsafe or unknown'; exit 1; }
ok "the PIA endpoint has a physical route via $ROUTE_DEVICE"

sudo -n nft list table inet "$TABLE" >/dev/null 2>&1 && { bad 'a previous test table exists'; exit 1; }
ok 'no previous automatic-reset table exists'

tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1 && ok 'public IPv4 works through the VPN before the test' || { bad 'public IPv4 does not work before the test'; exit 1; }

printf '\n--- Install temporary kill-switch table ---\n'
cat >"$TMP_RULES" <<NFT
table inet $TABLE {
  set allowed_endpoints_v4 { type ipv4_addr . inet_service; }
  set allowed_endpoints_v6 { type ipv6_addr . inet_service; }
  chain output {
    type filter hook output priority -100; policy accept;
    oifname "lo" counter accept comment "loopback"
    ip daddr . udp dport @allowed_endpoints_v4 oifname "$ROUTE_DEVICE" counter accept comment "allowed endpoint IPv4"
    ip6 daddr . udp dport @allowed_endpoints_v6 oifname "$ROUTE_DEVICE" counter accept comment "allowed endpoint IPv6"
    oifname "$VPN_IF" counter accept comment "VPN tunnel"
    counter reject with icmpx type admin-prohibited comment "block outside VPN"
  }
}
NFT
sudo -n nft -f "$TMP_RULES" || { bad 'the temporary nftables table could not be installed'; exit 1; }
TABLE_CREATED=1
ok 'the temporary automatic-reset kill-switch table was installed'

if [[ "$ENDPOINT_FAMILY" == IPv4 ]]; then
  sudo -n nft add element inet "$TABLE" allowed_endpoints_v4 "{ $ENDPOINT_IP . $ENDPOINT_PORT }"
else
  sudo -n nft add element inet "$TABLE" allowed_endpoints_v6 "{ $ENDPOINT_IP . $ENDPOINT_PORT }"
fi
ok 'the current PIA endpoint was added to the allow set'

tcp_probe 4 1.1.1.1 443 5 >/dev/null 2>&1 && ok 'VPN connectivity still works under protection' || { bad 'VPN connectivity failed after installing the table'; exit 1; }

printf '\n--- Arm independent root-owned reset ---\n'
cancel_timer
sudo -n systemd-run --quiet --unit="$UNIT" --on-active="${RESET_SECONDS}s" \
  /bin/bash -c '
    "$1" delete table inet pia_bazzite_killswitch_automatic_reset_test >/dev/null 2>&1 || true
    "$2" connection up uuid "$3" >/dev/null 2>&1 || true
  ' bash "$(command -v nft)" "$(command -v nmcli)" "$VPN_UUID" \
  || { bad 'the automatic reset timer could not be created'; exit 1; }
TIMER_CREATED=1
systemctl is-active --quiet "${UNIT}.timer" && ok "the automatic reset timer is active for ${RESET_SECONDS} seconds" || { bad 'the automatic reset timer is not active'; exit 1; }

printf '\n--- Enter deliberately blocked state ---\n'
if [[ "$ENDPOINT_FAMILY" == IPv4 ]]; then
  sudo -n nft delete element inet "$TABLE" allowed_endpoints_v4 "{ $ENDPOINT_IP . $ENDPOINT_PORT }"
else
  sudo -n nft delete element inet "$TABLE" allowed_endpoints_v6 "{ $ENDPOINT_IP . $ENDPOINT_PORT }"
fi
ok 'the PIA endpoint was removed from the allow set'

timeout 40s nmcli connection down uuid "$VPN_UUID" >/dev/null 2>&1 && ok 'NetworkManager deactivated the PIA profile' || warn 'NetworkManager returned an error while deactivating PIA'
sleep 3

BEFORE="$(block_packets)"; [[ "$BEFORE" =~ ^[0-9]+$ ]] || BEFORE=0
tcp_probe 4 1.1.1.1 443 4 >/dev/null 2>&1 && bad 'public IPv4 unexpectedly succeeded before reset' || ok 'public IPv4 is blocked while PIA is unavailable'
tcp_probe 6 2606:4700:4700::1111 443 4 >/dev/null 2>&1 && bad 'public IPv6 unexpectedly succeeded before reset' || ok 'public IPv6 is blocked while PIA is unavailable'
AFTER="$(block_packets)"; [[ "$AFTER" =~ ^[0-9]+$ ]] || AFTER=0
(( AFTER>BEFORE )) && ok "the block counter increased in the protected state ($BEFORE -> $AFTER)" || bad 'the block counter did not increase in the protected state'

printf '\n--- Wait for independent safety reset ---\n'
printf 'Waiting for the root-owned timer to fire after %ss ...\n' "$RESET_SECONDS"
REMOVED=0
for _ in $(seq 1 65); do
  if ! sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then REMOVED=1; break; fi
  sleep 1
done
if (( REMOVED==1 )); then TABLE_CREATED=0; ok 'the root-owned timer removed the nftables table automatically'; else bad 'the nftables table still exists after the reset deadline'; fi

RESULT="$(systemctl show "${UNIT}.service" --property=Result --value 2>/dev/null || true)"
[[ "$RESULT" == success ]] && ok 'the automatic reset service completed successfully' || bad "the automatic reset service result is '${RESULT:-unknown}'"

FRESH=0
for _ in $(seq 1 85); do
  if vpn_active; then
    TS="$(handshake)"
    if [[ "$TS" =~ ^[0-9]+$ && "$TS" -gt 0 ]]; then
      AGE=$(( $(date +%s) - TS ))
      if (( AGE>=0 && AGE<=40 )); then FRESH=1; break; fi
    fi
  fi
  sleep 1
done
(( FRESH==1 )) && ok 'WireGuard completed a fresh handshake after the automatic reset' || bad 'WireGuard did not complete a fresh handshake after the automatic reset'

tcp_probe 4 1.1.1.1 443 6 >/dev/null 2>&1 && ok 'public IPv4 returned through the restored VPN' || bad 'public IPv4 did not return after the reset'
systemctl is-active --quiet firewalld 2>/dev/null && ok 'firewalld remained active throughout the test' || warn 'firewalld is not active at the end'

printf '\n--- Final cleanup ---\n'
cancel_timer
sudo -n nft list table inet "$TABLE" >/dev/null 2>&1 && bad 'the temporary table unexpectedly remains' || ok 'no automatic-reset test table remains'
systemctl is-active --quiet "${UNIT}.timer" 2>/dev/null && bad 'the automatic reset timer is still active' || ok 'the automatic reset timer is no longer active'
vpn_active && ok 'PIA Bazzite WireGuard is connected at the end' || bad 'PIA Bazzite WireGuard is not connected at the end'

printf '\n--- Result ---\n'
printf 'Passed: %d\nWarnings: %d\nFailures: %d\n' "$PASS" "$WARN" "$FAIL"
if (( FAIL==0 )); then
  printf '\nALL AUTOMATIC SAFETY-RESET TESTS PASSED\n'
  printf 'The independent root-owned timer removed the blocking table, reactivated\n'
  printf 'PIA, obtained a fresh WireGuard handshake, and restored VPN connectivity.\n'
  exit 0
fi
printf '\nAUTOMATIC SAFETY-RESET TEST FAILED\n'
exit 1
