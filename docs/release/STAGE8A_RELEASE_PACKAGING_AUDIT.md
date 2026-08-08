# Stage 8A — 0.6.0 release and AppImage packaging audit

Stage 8A starts the final release stage after the Stage-7 crash/recovery gate.
It makes no firewall or NetworkManager changes.

## Audit findings

The Stage-7-complete tree was clean at commit `b4154cf` with tag
`stage7-crash-recovery-complete`.

The pre-8A AppImage metadata still targeted 0.5.0 and the AppImage contained the
GUI/runtime only. The Session Kill Switch, however, deliberately executes only a
fixed root-owned helper under `/usr/local/libexec/pia-bazzite`. Therefore a 0.6.0
AppImage must carry the exact helper installation payload even though it must not
execute that payload directly from the AppImage mount.

## Stage-8A invariants

- Runtime and active release metadata identify version 0.6.0.
- A release tag must exactly match the runtime version (`v0.6.0`).
- The AppImage builder carries only the production helper/session launchers,
  production helper Python package, and fixed installer.
- A build-time `bundle-manifest.json` records the application version, helper
  stage, protocol version, and SHA-256 of every payload file.
- The helper payload is not installed or executed by this stage.
- Existing 0.5.0 changelog/AppStream history remains intact.

Stage 8B owns the explicit authenticated install/upgrade flow and the first real
host test from the built AppImage.
