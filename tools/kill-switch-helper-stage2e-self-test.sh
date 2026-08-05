#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
REPORT="$ROOT/test-results/kill-switch/stage2-polkit/pia-kill-switch-helper-stage2e-self-test.txt"
mkdir -p "$(dirname -- "$REPORT")"
exec > >(tee "$REPORT") 2>&1

printf 'PIA Bazzite stage-2E security-boundary self-test\n'
printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
printf 'This test is unprivileged and does not touch authorization, networking, NetworkManager, or nftables.\n\n'

cd "$ROOT"
printf '%s\n' '--- Python syntax ---'
mapfile -t python_files < <(find helper tests -type f -name '*.py' -print | sort)
"$PYTHON" -m py_compile "${python_files[@]}"
printf 'PASS  compiled %d Python files\n\n' "${#python_files[@]}"

printf '%s\n' '--- Shell syntax ---'
bash -n \
  tools/pia-bazzite-stage2-helper-installer.sh \
  tools/kill-switch-helper-stage2e-self-test.sh \
  tools/kill-switch-helper-stage2e-security-test.sh \
  tools/kill-switch-helper-stage2d2-self-test.sh \
  tools/kill-switch-helper-stage2d2-namespace-test.sh
printf 'PASS  stage-2E and regression shell scripts parse\n\n'

printf '%s\n' '--- Helper, bootstrap, installer, and Polkit unit tests ---'
"$PYTHON" -m unittest discover -s tests/helper -v
"$PYTHON" -m unittest discover -s tests/polkit -v
printf '\n'

printf '%s\n' '--- Existing PIA Bazzite v0.5.0 regression self-test ---'
"$PYTHON" self_test.py
printf '\nALL STAGE-2E UNPRIVILEGED SELF-TESTS PASSED\n'
printf 'Report: %s\n' "$REPORT"
