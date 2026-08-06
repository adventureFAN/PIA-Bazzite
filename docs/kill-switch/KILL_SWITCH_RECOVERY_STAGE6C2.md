# Kill Switch recovery Stage 6C.2

Stage 6C.2 fixes two fail-closed usability problems found by the real GUI sentinel test.

## Existing-instance gate

The real GUI harness probes the authoritative Qt local-server socket before `sudo`,
helper installation, the safety timer, and again immediately before launching the
test GUI. A live PIA Bazzite instance makes the test stop before any production
firewall lock can be created. Stale socket files do not count because a connection
must succeed.

## Emergency Reset reconciliation

A GUI process can retain a conservative red state after an external documented
Emergency Reset. It must not infer that the firewall disappeared. When the VPN is
down and no complete in-memory reconnect context exists, the main action becomes
**Recheck protection status**. This invokes only the fixed installed helper's
read-only `status` operation.

- Verified table present: keep the error/blocking state and do not close.
- Status unavailable or unverified: keep the error state and do not close.
- Verified table absent: discard stale in-memory baseline/route data, show the armed
  state, and permit a requested quit.

The reconciliation path contains no enable, disable, emergency-reset, or arbitrary
shell action.
