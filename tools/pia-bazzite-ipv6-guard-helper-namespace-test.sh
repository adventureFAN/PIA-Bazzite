#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/release/stage8"
REPORT="$REPORT_DIR/pia-bazzite-stage8c3-ipv6-guard-helper-namespace-test.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite Stage-8C.3 IPv6 guard helper namespace test\n'
printf 'This test uses sudo only to create an isolated network namespace.\n'
printf 'It cannot modify the host nftables ruleset or NetworkManager.\n\n'

for tool in sudo unshare nft python3; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'FAIL: required tool missing: %s\n' "$tool"
    exit 1
  }
done
printf 'PASS: required tools are available\n'

sudo -v
printf 'PASS: sudo authorization available\n'

sudo ROOT="$ROOT" unshare --net -- bash -s <<'NS'
set -Eeuo pipefail

HELPER="$ROOT/helper/pia-bazzite-kill-switch-helper"
TABLE="pia_bazzite_ipv6_guard"
KILL_TABLE="pia_bazzite_killswitch"

json_assert() {
  local document="$1"
  local action="$2"
  local state="$3"
  python3 - "$document" "$action" "$state" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload["ok"] is True, payload
assert payload["action"] == sys.argv[2], payload
assert payload["state"] == sys.argv[3], payload
assert payload["verified"] is True, payload
assert payload["table"] == "pia_bazzite_ipv6_guard", payload
assert payload["capabilities"] == ["ipv6-only-guard"], payload
PY
}

if nft list table inet "$KILL_TABLE" >/dev/null 2>&1; then
  echo 'FAIL: full Kill Switch table unexpectedly exists in fresh namespace'
  exit 1
fi
echo 'PASS: full Kill Switch table absent before guard test'

status="$($HELPER ipv6-guard-status)"
json_assert "$status" ipv6-guard-status disabled
echo 'PASS: guard status starts disabled'

enabled="$($HELPER ipv6-guard-enable)"
json_assert "$enabled" ipv6-guard-enable active
echo 'PASS: helper enabled and verified fixed IPv6 guard table'

rules="$(nft list chain inet "$TABLE" output)"
grep -Fq 'pia-bazzite:ipv6-guard:v1:loopback' <<<"$rules"
grep -Fq 'pia-bazzite:ipv6-guard:v1:block-ipv6' <<<"$rules"
grep -Fq 'meta nfproto ipv6' <<<"$rules"
echo 'PASS: exact IPv6-only rule markers are present'

if nft list table inet "$KILL_TABLE" >/dev/null 2>&1; then
  echo 'FAIL: IPv6 guard action created or touched full Kill Switch table'
  exit 1
fi
echo 'PASS: full Kill Switch table remains absent while guard is active'

checked="$($HELPER ipv6-guard-status)"
json_assert "$checked" ipv6-guard-status active
echo 'PASS: separate guard status re-verifies active table'

disabled="$($HELPER ipv6-guard-disable)"
json_assert "$disabled" ipv6-guard-disable disabled
echo 'PASS: helper disabled and verified fixed IPv6 guard table'

if nft list table inet "$TABLE" >/dev/null 2>&1; then
  echo 'FAIL: IPv6 guard table still exists after disable'
  exit 1
fi
echo 'PASS: IPv6 guard table absent after disable'
NS

printf '\nALL STAGE-8C.3 IPV6 GUARD HELPER NAMESPACE TESTS PASSED\n'
printf 'The host firewall, NetworkManager, PIA VPN profile, and production Kill Switch table were not modified.\n'
printf 'Report: %s\n' "$REPORT"
