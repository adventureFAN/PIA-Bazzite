# Restricted kill-switch helper

This directory contains the staged privileged-helper prototype for the PIA
Bazzite session kill switch.

## Stage 1

The project launcher `pia-bazzite-kill-switch-helper` refuses the host network
namespace and is used only by the isolated stage-1 namespace test:

```bash
./tools/kill-switch-helper-stage1-namespace-test.sh
```

## Stage 2C

The separate launcher `pia-bazzite-kill-switch-helper-installed` is installed
root-owned at the fixed path `/usr/local/libexec/pia-bazzite/` by the explicit
stage-2C test installer. It requires a valid `pkexec` invocation, verifies its
installed files and checksum manifest, and still refuses the host network
namespace.

```bash
./tools/kill-switch-polkit-stage2-helper-self-test.sh
./tools/kill-switch-polkit-stage2-helper-namespace-test.sh
```

Neither launcher is connected to the PySide6 application yet. The helper still
uses only the fixed test table `pia_bazzite_killswitch_helper_test`.

Design and test details are documented in:

- `docs/kill-switch/HELPER_STAGE1.md`
- `docs/kill-switch/POLKIT_STAGE2.md`
