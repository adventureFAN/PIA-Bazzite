#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/tools/pia-bazzite-stage2-polkit-probe-installer.sh"
TARGET="/usr/local/libexec/pia-bazzite/pia-bazzite-auth-probe"
REPORT_DIR="$ROOT/test-results/kill-switch/stage2-polkit"
REPORT="$REPORT_DIR/pia-kill-switch-polkit-stage2-auth-test.txt"
mkdir -p "$REPORT_DIR"

PASS=0
FAIL=0
INSTALLED=0

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$*"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }

cleanup() {
  if [ "$INSTALLED" -eq 1 ]; then
    echo
    echo "--- Cleanup ---"
    if sudo "$INSTALLER" uninstall; then
      INSTALLED=0
      pass "root-owned auth probe removed"
    else
      fail "could not remove root-owned auth probe"
    fi
  fi
}
trap cleanup EXIT

run_test() {
  echo "PIA Bazzite stage-2 Polkit authorization test"
  echo "Generated: $(date --iso-8601=seconds)"
  echo "This test installs one network-free probe under /usr/local/libexec."
  echo "It does not call nftables or NetworkManager."
  echo

  echo "--- Preconditions ---"
  if command -v pkexec >/dev/null 2>&1; then pass "pkexec is available"; else fail "pkexec is missing"; fi
  if pgrep -u "$(id -u)" -f 'polkit.*agent|polkit-kde' >/dev/null 2>&1; then
    pass "graphical Polkit authentication agent is running"
  else
    fail "no graphical Polkit authentication agent detected"
  fi

  if [ "$FAIL" -ne 0 ]; then
    echo "Preconditions failed; privileged test was not started."
    return 1
  fi

  echo
  echo "--- Unprivileged input checks ---"
  set +e
  invalid_output="$("$ROOT/helper/pia-bazzite-polkit-probe" not-an-action 2>&1)"
  invalid_code=$?
  direct_output="$("$ROOT/helper/pia-bazzite-polkit-probe" status 2>&1)"
  direct_code=$?
  set -e
  if [ "$invalid_code" -eq 2 ]; then pass "invalid action rejected before privilege"; else fail "invalid action exit code was $invalid_code"; fi
  if [ "$direct_code" -eq 3 ]; then pass "direct unprivileged execution rejected"; else fail "direct execution exit code was $direct_code"; fi

  echo
  echo "--- Root-owned installation ---"
  sudo "$INSTALLER" install
  INSTALLED=1
  if [ -f "$TARGET" ] && [ ! -L "$TARGET" ]; then pass "fixed installed path is a regular file"; else fail "installed target is missing or unsafe"; fi
  if [ "$(stat -c '%u:%g:%a' -- "$TARGET")" = "0:0:755" ]; then
    pass "installed probe is root:root mode 0755"
  else
    fail "installed probe ownership or mode is unexpected"
  fi

  echo
  echo "--- Graphical Polkit authorization ---"
  echo "A graphical password dialog should appear now."
  set +e
  authorized_output="$(pkexec "$TARGET" status 2>&1)"
  authorized_code=$?
  set -e
  printf '%s\n' "$authorized_output"
  if [ "$authorized_code" -eq 0 ]; then
    pass "pkexec authorized and executed the fixed installed probe"
  else
    fail "pkexec returned exit code $authorized_code"
  fi

  if /usr/bin/python3 -c '
import json, sys
from pathlib import Path
p=json.loads(sys.stdin.read())
assert p["ok"] is True
assert p["euid"] == 0
assert p["pkexec_verified"] is True
assert p["ownership_verified"] is True
assert p["network_access"] is False
assert p["nftables_access"] is False
expected = Path("/usr/local/libexec/pia-bazzite/pia-bazzite-auth-probe").resolve(strict=True)
actual = Path(p["installed_path"])
assert actual == expected, f"installed path mismatch: {actual} != {expected}"
' <<<"$authorized_output"; then
    pass "probe JSON verifies root, pkexec, ownership, and no network access"
  else
    fail "probe JSON verification failed"
  fi

  echo
  echo "--- Explicit cleanup ---"
  sudo "$INSTALLER" uninstall
  INSTALLED=0
  if [ ! -e "$TARGET" ]; then pass "installed probe removed"; else fail "installed probe remains"; fi

  echo
  echo "--- Result ---"
  echo "PASS: $PASS"
  echo "FAIL: $FAIL"
  if [ "$FAIL" -eq 0 ]; then
    echo "ALL STAGE-2 POLKIT AUTHORIZATION TESTS PASSED"
    return 0
  fi
  echo "STAGE-2 POLKIT AUTHORIZATION TEST FAILED"
  return 1
}

exec > >(tee "$REPORT") 2>&1
set +e
run_test
result=$?
set -e
echo "Report: $REPORT"
exit "$result"
