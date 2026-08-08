#!/usr/bin/env bash
set -u

INTERFACE="piabazzite"
CONNECTION="PIA Bazzite"
TARGET4="1.1.1.1"
TARGET6="2606:4700:4700::1111"

if command -v xdg-user-dir >/dev/null 2>&1; then
  DOWNLOAD_DIR="$(xdg-user-dir DOWNLOAD 2>/dev/null || true)"
else
  DOWNLOAD_DIR=""
fi
[[ -n "$DOWNLOAD_DIR" ]] || DOWNLOAD_DIR="$HOME/Downloads"
mkdir -p "$DOWNLOAD_DIR"
OUT="${1:-$DOWNLOAD_DIR/PIA-Bazzite-network-debug.txt}"

redact_route() {
  sed -E \
    -e 's/( src )[0-9A-Fa-f:.]+/\1<redacted>/g' \
    -e 's/( from )[0-9A-Fa-f:.]+/\1<redacted>/g'
}

section() {
  printf '\n=== %s ===\n' "$1"
}

{
  echo "PIA Bazzite read-only network diagnostic"
  date --iso-8601=seconds 2>/dev/null || date
  echo "This report never prints PIA credentials, WireGuard private keys, or the user's public IP address."
  echo "It performs no privileged or firewall mutation. nftables ownership is verified by the app/helper, not by this unprivileged report."

  section "NetworkManager connection state"
  nmcli -t -f UUID,NAME,TYPE connection show --active 2>&1 \
    | awk -F: -v name="$CONNECTION" '$2 == name && $3 == "wireguard" {print "PIA active UUID: "$1; found=1} END {if (!found) print "PIA active UUID: none"}'

  if nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep -Fxq "$CONNECTION:wireguard"; then
    echo
    nmcli -f \
connection.id,connection.uuid,connection.interface-name,connection.autoconnect,\
ipv4.method,ipv4.never-default,ipv4.route-table,ipv4.dns-priority,ipv4.dns-search,\
ipv6.method,ipv6.never-default,\
wireguard.peer-routes,wireguard.ip4-auto-default-route,wireguard.ip6-auto-default-route \
      connection show "$CONNECTION" 2>&1 \
      | sed -E 's/(connection\.uuid:[[:space:]]*).*/\1<redacted>/'
  else
    echo "PIA WireGuard profile is not present."
  fi

  section "WireGuard runtime (no keys)"
  if command -v wg >/dev/null 2>&1 && ip link show "$INTERFACE" >/dev/null 2>&1; then
    printf 'interface: %s\n' "$INTERFACE"
    printf 'endpoint(s):\n'
    wg show "$INTERFACE" endpoints 2>/dev/null | awk '{print "  "$2}' || true
    printf 'allowed IPs:\n'
    wg show "$INTERFACE" allowed-ips 2>/dev/null | cut -f2- | sed 's/^/  /' || true
    printf 'latest handshake(s):\n'
    wg show "$INTERFACE" latest-handshakes 2>/dev/null | awk '{print "  "$2}' || true
  else
    echo "WireGuard interface is not active."
  fi

  section "Effective public routing decisions"
  echo "IPv4:"
  ip -4 route get "$TARGET4" 2>&1 | redact_route || true
  echo "IPv6 (a physical route may still be selected; the normal-mode firewall guard blocks egress):"
  ip -6 route get "$TARGET6" 2>&1 | redact_route || true

  section "Policy routing rules"
  echo "IPv4 rules:"
  ip -4 rule show 2>&1 || true
  echo "IPv6 rules:"
  ip -6 rule show 2>&1 || true

  section "DNS for PIA interface"
  if command -v resolvectl >/dev/null 2>&1; then
    resolvectl dns "$INTERFACE" 2>&1 || true
    resolvectl domain "$INTERFACE" 2>&1 || true
  else
    echo "resolvectl not available"
  fi

  section "Public egress family check (country only, no IP printed)"
  for family in 4 6; do
    printf 'IPv%s: ' "$family"
    payload="$(curl "-$family" -fsS --max-time 8 https://api.country.is/ 2>/dev/null || true)"
    if [[ -z "$payload" ]]; then
      echo "BLOCKED/UNAVAILABLE"
      continue
    fi
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("country", "UNKNOWN"))' <<<"$payload" 2>/dev/null || echo "INVALID_RESPONSE"
  done

  section "Interpretation hints"
  echo "Expected while PIA is connected WITHOUT Session Kill Switch:"
  echo "  IPv4 route -> dev piabazzite"
  echo "  IPv6 route may still name the physical interface, but the verified IPv6-only nftables guard must block actual IPv6 egress"
  echo "  IPv4 country -> selected PIA region; IPv6 -> BLOCKED/UNAVAILABLE"
  echo "Expected after an intentional normal-VPN disconnect:"
  echo "  PIA profile inactive and normal system IPv4/IPv6 egress restored"
  echo "With Session Kill Switch active, its separate full nftables firewall is authoritative for IPv4 and IPv6 fail-closed protection."
} | tee "$OUT"

printf '\nSaved diagnostic: %s\n' "$OUT"
