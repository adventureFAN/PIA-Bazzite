#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALLER="$ROOT/tools/pia-bazzite-stage2-helper-installer.sh"
TARGET="/usr/local/libexec/pia-bazzite"
PACKAGE="$TARGET/pia_bazzite_kill_switch_helper"
LAUNCHER="$TARGET/pia-bazzite-kill-switch-helper"
MANIFEST="$TARGET/kill-switch-helper-manifest.json"
CORE="$PACKAGE/core.py"
PROTOCOL="$PACKAGE/protocol.py"
TABLE="pia_bazzite_killswitch"
RUN_ID="$$"
CORE_BACKUP="/run/pia-bazzite-stage2e-core-$RUN_ID.py"
PROTOCOL_BACKUP="/run/pia-bazzite-stage2e-protocol-$RUN_ID.py"
MANIFEST_BACKUP="/run/pia-bazzite-stage2e-manifest-$RUN_ID.json"
SENTINEL="$TARGET/stage2e-unknown-sentinel"
REPORT="$ROOT/test-results/kill-switch/stage2-polkit/pia-kill-switch-helper-stage2e-security-test.txt"
PASS=0
FAIL=0
CORE_DIRTY=0
PROTOCOL_DIRTY=0
MANIFEST_DIRTY=0
SYMLINK_ACTIVE=0

mkdir -p "$(dirname -- "$REPORT")"
exec > >(tee "$REPORT") 2>&1

pass() { printf 'PASS  %s\n' "$*"; PASS=$((PASS + 1)); }
fail() { printf 'FAIL  %s\n' "$*"; FAIL=$((FAIL + 1)); }

root_harness() {
  sudo -n /usr/bin/env -i \
    "PKEXEC_UID=$(id -u)" \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    LC_ALL=C \
    "$LAUNCHER" "$@"
}

json_error_is() {
  local expected="$1" pattern="$2"
  python3 -c '
import json,sys
expected=sys.argv[1]
pattern=sys.argv[2]
p=json.load(sys.stdin)
assert p["ok"] is False
assert p["error"] == expected
assert pattern.lower() in p["message"].lower()
' "$expected" "$pattern"
}

restore_file() {
  local backup="$1" target="$2" mode="$3"
  if [[ -f "$backup" ]]; then
    sudo -n /usr/bin/install -o root -g root -m "$mode" -- "$backup" "$target" || true
    sudo -n /usr/bin/rm -f -- "$backup" || true
  fi
}

cleanup() {
  set +e
  if [[ $SYMLINK_ACTIVE -eq 1 && -L "$PROTOCOL" ]]; then
    sudo -n /usr/bin/rm -f -- "$PROTOCOL"
  fi
  if [[ $CORE_DIRTY -eq 1 ]]; then restore_file "$CORE_BACKUP" "$CORE" 0644; fi
  if [[ $PROTOCOL_DIRTY -eq 1 || $SYMLINK_ACTIVE -eq 1 ]]; then
    restore_file "$PROTOCOL_BACKUP" "$PROTOCOL" 0644
  fi
  if [[ $MANIFEST_DIRTY -eq 1 ]]; then restore_file "$MANIFEST_BACKUP" "$MANIFEST" 0644; fi
  sudo -n /usr/bin/rm -f -- "$SENTINEL" "$CORE_BACKUP" "$PROTOCOL_BACKUP" "$MANIFEST_BACKUP" 2>/dev/null
  if [[ -x "$INSTALLER" ]]; then sudo -n "$INSTALLER" uninstall >/dev/null 2>&1; fi
  sudo -n /usr/bin/rmdir --ignore-fail-on-non-empty "$PACKAGE" "$TARGET" 2>/dev/null
}
trap cleanup EXIT

printf 'PIA Bazzite stage-2E installation and authorization security test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test does not create firewall rules or change NetworkManager.\n'
printf 'One graphical Polkit dialog must be deliberately cancelled.\n\n'

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  printf 'Run this test as the desktop user, not as root.\n' >&2
  exit 1
fi
for command in sudo pkexec pkcheck timeout nft python3; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 1; }
done

printf '%s\n' '--- One-time privilege cache and clean start ---'
sudo -v || exit 1
sudo -n "$INSTALLER" uninstall >/dev/null 2>&1 || true
sudo -n /usr/bin/rm -f -- "$SENTINEL"
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "host unexpectedly contains the fixed helper test table"
else
  pass "host does not contain the fixed helper test table"
fi
sudo -n "$INSTALLER" install
[[ -x "$LAUNCHER" ]] && pass "root-owned restricted helper installed" || fail "helper installation missing"
printf '\n'

printf '%s\n' '--- Direct execution boundaries ---'
set +e
direct_output="$("$LAUNCHER" status 2>&1)"
direct_code=$?
set -e
if [[ $direct_code -eq 3 ]] && json_error_is privilege "pkexec" <<<"$direct_output"; then
  pass "direct unprivileged execution is refused with stable JSON"
else
  printf '%s\n' "$direct_output"
  fail "direct unprivileged execution was not refused as expected"
fi
set +e
clean_output="$(root_harness status 2>&1)"
clean_code=$?
set -e
if [[ $clean_code -eq 6 ]] && json_error_is safety-boundary "host network namespace" <<<"$clean_output"; then
  pass "clean bootstrap verifies installation before the helper refuses the host namespace"
else
  printf '%s\n' "$clean_output"
  fail "clean installed bootstrap did not reach the expected host safety boundary"
fi
printf '\n'

printf '%s\n' '--- Deliberately denied graphical Polkit authorization ---'
pkcheck --revoke-temp >/dev/null 2>&1 || true
printf 'A graphical password dialog should appear. Click Cancel / Abbrechen.\n'
set +e
deny_output="$(LC_ALL=C timeout 60s pkexec --disable-internal-agent "$LAUNCHER" status 2>&1)"
deny_code=$?
set -e
printf '%s\n' "$deny_output"
if [[ $deny_code -eq 126 ]]; then
  pass "dismissed Polkit dialog prevented helper execution"
elif [[ $deny_code -eq 127 && "$deny_output" == *"Not authorized"* ]]; then
  pass "Polkit denial prevented helper execution (agent reported not authorized)"
elif [[ $deny_code -eq 124 ]]; then
  fail "Polkit denial test timed out instead of being cancelled"
else
  fail "dismissed Polkit dialog returned unexpected exit code $deny_code"
fi
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "authorization denial created a host firewall table"
else
  pass "authorization denial left the host firewall unchanged"
fi
printf '\n'

printf '%s\n' '--- Checksum tamper is rejected before package import ---'
sudo -n /usr/bin/install -o root -g root -m 0644 -- "$CORE" "$CORE_BACKUP"
CORE_DIRTY=1
printf '\n# stage2e checksum tamper\n' | sudo -n /usr/bin/tee -a "$CORE" >/dev/null
set +e
tamper_output="$(root_harness status 2>&1)"
tamper_code=$?
set -e
printf '%s\n' "$tamper_output"
if [[ $tamper_code -eq 6 ]] && json_error_is installation-boundary "checksum mismatch" <<<"$tamper_output"; then
  pass "modified module is rejected by the standalone bootstrap checksum"
else
  fail "modified module was not rejected before import"
fi
restore_file "$CORE_BACKUP" "$CORE" 0644
CORE_DIRTY=0
printf '\n'

printf '%s\n' '--- Unsafe installed mode is rejected ---'
sudo -n /usr/bin/install -o root -g root -m 0644 -- "$PROTOCOL" "$PROTOCOL_BACKUP"
PROTOCOL_DIRTY=1
sudo -n /usr/bin/chmod 0666 -- "$PROTOCOL"
set +e
mode_output="$(root_harness status 2>&1)"
mode_code=$?
set -e
printf '%s\n' "$mode_output"
if [[ $mode_code -eq 6 ]] && json_error_is installation-boundary "mode" <<<"$mode_output"; then
  pass "group/world-writable installed module is rejected"
else
  fail "unsafe installed module mode was not rejected"
fi
restore_file "$PROTOCOL_BACKUP" "$PROTOCOL" 0644
PROTOCOL_DIRTY=0
printf '\n'

printf '%s\n' '--- Wrong manifest identity is rejected ---'
sudo -n /usr/bin/install -o root -g root -m 0644 -- "$MANIFEST" "$MANIFEST_BACKUP"
MANIFEST_DIRTY=1
sudo -n /usr/bin/python3 -I - "$MANIFEST" <<'PY'
import json,sys
path=sys.argv[1]
with open(path, encoding='utf-8') as handle:
    payload=json.load(handle)
payload['helper_stage']=999
with open(path, 'w', encoding='utf-8') as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write('\n')
PY
set +e
manifest_output="$(root_harness status 2>&1)"
manifest_code=$?
set -e
printf '%s\n' "$manifest_output"
if [[ $manifest_code -eq 6 ]] && json_error_is installation-boundary "stage" <<<"$manifest_output"; then
  pass "manifest from a different helper stage is rejected"
else
  fail "wrong manifest identity was not rejected"
fi
restore_file "$MANIFEST_BACKUP" "$MANIFEST" 0644
MANIFEST_DIRTY=0
printf '\n'

printf '%s\n' '--- Uninstaller preflights every known path before deletion ---'
sudo -n /usr/bin/install -o root -g root -m 0644 -- "$PROTOCOL" "$PROTOCOL_BACKUP"
PROTOCOL_DIRTY=1
sudo -n /usr/bin/rm -f -- "$PROTOCOL"
sudo -n /usr/bin/ln -s /etc/hosts "$PROTOCOL"
SYMLINK_ACTIVE=1
set +e
uninstall_output="$(sudo -n "$INSTALLER" uninstall 2>&1)"
uninstall_code=$?
set -e
printf '%s\n' "$uninstall_output"
if [[ $uninstall_code -ne 0 && -e "$LAUNCHER" && -e "$MANIFEST" ]]; then
  pass "symlink target aborts uninstall before any known helper file is deleted"
else
  fail "uninstaller did not fail atomically on a symlink target"
fi
sudo -n /usr/bin/rm -f -- "$PROTOCOL"
SYMLINK_ACTIVE=0
restore_file "$PROTOCOL_BACKUP" "$PROTOCOL" 0644
PROTOCOL_DIRTY=0
printf '\n'

printf '%s\n' '--- Uninstaller removes only its fixed known files ---'
sudo -n /usr/bin/install -o root -g root -m 0600 /dev/null "$SENTINEL"
if sudo -n "$INSTALLER" uninstall; then
  if [[ -f "$SENTINEL" && ! -e "$LAUNCHER" && ! -e "$MANIFEST" ]]; then
    pass "unknown root-owned sentinel survives while all known helper files are removed"
  else
    fail "uninstaller scope did not match the fixed known file list"
  fi
else
  fail "normal controlled uninstall failed"
fi
sudo -n /usr/bin/rm -f -- "$SENTINEL"
sudo -n /usr/bin/rmdir --ignore-fail-on-non-empty "$PACKAGE" "$TARGET" 2>/dev/null || true
printf '\n'

printf '%s\n' '--- Final host safety check ---'
if sudo -n nft list table inet "$TABLE" >/dev/null 2>&1; then
  fail "host contains the fixed helper test table after stage-2E"
else
  pass "host firewall remains free of the helper test table"
fi
if [[ ! -e "$LAUNCHER" && ! -e "$MANIFEST" ]]; then
  pass "root-owned stage-2E test installation is absent"
else
  fail "stage-2E test installation remains"
fi

printf '\n--- Result ---\n'
printf 'PASS: %d\nFAIL: %d\n' "$PASS" "$FAIL"
if [[ $FAIL -eq 0 ]]; then
  printf 'ALL STAGE-2E SECURITY-BOUNDARY TESTS PASSED\n'
  printf 'Report: %s\n' "$REPORT"
  exit 0
fi
printf 'STAGE-2E SECURITY-BOUNDARY TEST FAILED\n'
exit 1
