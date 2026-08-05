# Restricted kill-switch helper (stage 1)

This directory contains the test-only privileged-helper prototype for the PIA
Bazzite session kill switch.

Do not install it system-wide and do not connect it to polkit yet. The launcher
refuses the host network namespace and is intended only for:

```bash
./tools/kill-switch-helper-stage1-namespace-test.sh
```

Design and test details are documented in:

`docs/kill-switch/HELPER_STAGE1.md`
