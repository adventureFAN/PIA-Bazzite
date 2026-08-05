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

## Protocol v1 milestone

Stage 2D.1 adds a deterministic JSON protocol envelope for every normal helper
result and every handled failure. The host-network safety refusal remains in
place; see `docs/kill-switch/HELPER_PROTOCOL_V1.md`.

## Stage 2D.2 candidate table structure

The helper now renders the intended set-based firewall structure while still
refusing the host network namespace and retaining the isolated test table name.
The physical uplinks and exact WireGuard endpoints live in dedicated nftables
sets so the helper can replace them atomically without rebuilding unrelated
rules.

```bash
./tools/kill-switch-helper-stage2d2-self-test.sh
./tools/kill-switch-helper-stage2d2-namespace-test.sh
```

The new fixed protocol actions are `set-interfaces` and `set-endpoints`. Host
operation, GUI integration, and a production table name remain disabled.

## Stage 2E installation boundary

Stage 2E moves the checksum and ownership verification into the standalone
installed launcher before any helper package module is imported. The manifest
now binds the installation format, helper stage, protocol version, and exact
file list. The installer serializes operations with a lock and preflights every
known file before uninstalling anything.

```bash
./tools/kill-switch-helper-stage2e-self-test.sh
./tools/kill-switch-helper-stage2e-security-test.sh
```

The interactive security test deliberately cancels one graphical Polkit prompt,
then checks checksum tampering, unsafe modes, wrong manifest identity, symlink
uninstall refusal, and preservation of unknown files. It never creates a
firewall table and does not use NetworkManager.
