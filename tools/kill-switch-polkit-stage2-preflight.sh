#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$ROOT/test-results/kill-switch/stage2-polkit"
REPORT="$REPORT_DIR/pia-stage2-polkit-preflight.txt"
mkdir -p "$REPORT_DIR"

run_preflight() {
  echo "PIA Bazzite stage-2 Polkit preflight"
  echo "Generated: $(date --iso-8601=seconds)"
  echo

  echo "=== Git state ==="
  git -C "$ROOT" status --short --branch
  echo

  echo "=== Bazzite / rpm-ostree deployment ==="
  rpm-ostree status 2>&1 | sed -n '1,24p'
  echo

  echo "=== Required programs ==="
  for program in pkexec pkaction python3 nft install rpm-ostree; do
    if path="$(command -v "$program" 2>/dev/null)"; then
      printf '%-12s %s\n' "$program:" "$path"
    else
      printf '%-12s %s\n' "$program:" "NOT FOUND"
    fi
  done
  echo

  echo "=== Versions ==="
  pkexec --version 2>&1 || true
  python3 --version 2>&1 || true
  nft --version 2>&1 || true
  echo

  echo "=== Filesystem layout ==="
  for path in / /usr /usr/local /etc /var; do
    echo "--- $path"
    printf 'Resolved: '
    readlink -f "$path" 2>&1 || true
    printf 'Mount:    '
    findmnt -T "$path" -no TARGET,SOURCE,FSTYPE,OPTIONS 2>&1 || true
  done
  echo

  echo "=== Candidate installation locations ==="
  for path in \
    /usr/local \
    /usr/local/libexec \
    /usr/share/polkit-1/actions \
    /etc/polkit-1/actions \
    /usr/local/share/polkit-1/actions \
    /etc/polkit-1/rules.d
  do
    if [ -e "$path" ] || [ -L "$path" ]; then
      stat -c '%A  %U:%G  %n -> %N' "$path"
    else
      echo "MISSING  $path"
    fi
  done
  echo

  echo "=== Installed Polkit packages ==="
  rpm -qa | grep -Ei '^(polkit|polkit-kde)' | sort \
    || echo "No matching RPM package names found"
  echo

  echo "=== Default pkexec action ==="
  pkaction --action-id org.freedesktop.policykit.exec --verbose 2>&1 || true
  echo

  echo "=== Graphical authentication agent ==="
  ps -u "$USER" -o pid=,comm=,args= |
    grep -Ei 'polkit.*agent|polkit-kde' |
    grep -v grep \
    || echo "No obvious agent process found"
  echo

  echo "=== Existing PIA Bazzite system installation ==="
  find /usr/local/libexec /etc/polkit-1 /usr/share/polkit-1/actions \
    -maxdepth 2 \
    \( -iname '*pia*bazzite*' -o -iname '*kill*switch*' \) \
    -print 2>/dev/null \
    || true
}

run_preflight 2>&1 | tee "$REPORT"
echo "Report: $REPORT"
