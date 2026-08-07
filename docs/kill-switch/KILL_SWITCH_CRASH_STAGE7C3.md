# Kill Switch crash takeover Stage 7C.3

**Status:** Production transport-liveness and post-handoff hardening retained. Its original external process-discovery proof is superseded by Stage 7C.4.


The Stage-7C.2 result remained fail-closed but disproved the ancestry-only
process check. A restricted helper may remain usable even when `pkexec` changes
its process relationship. Conversely, a cached ready frame alone is not proof
that the transport process is still alive.

Stage 7C.3 hardens both sides of that boundary.

## Production handoff hardening

`KillSwitchSessionClient.is_open` now consults the real transport process rather
than only the cached ready frame. During startup adoption the GUI retains the
exact session object and then performs one additional read-only `status`
exchange from the GUI thread. The recovery session ID is rotated only after
that post-handoff status exactly matches the worker's last verified status.

A failure does not stop the VPN or remove the firewall. It leaves the host
fail-closed and does not claim adoption.

## Pipe-bound ownership proof

The real host test no longer requires the root helper to remain a process-tree
descendant. Through the already-authorized read-only `sudo -n` boundary it
inspects `/proc` and requires exactly one helper whose three private stdio pipes
are all still held by the restarted GUI process:

1. helper stdin is connected to a pipe held by the GUI;
2. helper stdout is connected to a second pipe held by the GUI;
3. helper stderr is connected to a third pipe held by the GUI;
4. the same helper PID, rotated recovery record, NetworkManager profile,
   firewall route, and independent leak sentinel remain stable together.

This proves the live transport even if `pkexec` reparents the helper. If no
pipe-bound helper exists, the failure report includes a root-visible candidate
summary while the firewall remains active.

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c3-self-test.sh
```

Then run the real host test:

```bash
bash tools/kill-switch-crash-stage7c3-host-test.sh
```

For an immediate deliberate reset after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c3-emergency-reset.sh
```
