# Kill-switch production boundary and real host test — Stage 5B

Stage 5B is deliberately split into two gates. The first gate is a completely
unprivileged regression self-test. The second gate is the first controlled use
of the production nftables table on the real Bazzite host. The normal PIA
Bazzite GUI connection button is **not** changed in this stage.

## What changes

- The helper identity advances to helper stage 5.
- The fixed table changes from the historical namespace-only test name to
  `inet pia_bazzite_killswitch`.
- Direct project launchers still refuse the host network namespace.
- Only the installed, root-owned and checksum-verified `pkexec` launchers may
  pass the internal trusted-host flag.
- The connection orchestrator gains a deliberate disconnect path that keeps the
  firewall active until the stopped VPN and the blocked ordinary path have both
  been verified.
- Physical-interface discovery uses `ip route get` with the exact numeric
  WireGuard endpoint before the firewall is enabled.

The helper still has no general command, shell, arbitrary nftables script, table
name, chain name, interface, or endpoint escape hatch. Every accepted value is
validated and only the fixed ruleset can be rendered.

## Gate 1: unprivileged self-test

Run:

```bash
cd /home/alex/PIA-Bazzite
bash tools/kill-switch-connection-stage5b-self-test.sh
```

This gate must finish with:

```text
SELF-TEST PASSED
ALL STAGE-5B SELF-TESTS PASSED
No host firewall or VPN connection was changed by this self-test.
```

It never invokes `sudo`, `pkexec`, NetworkManager, PIA, or nftables.

## Gate 2: controlled real host test

Prerequisites:

1. Close the normal PIA Bazzite application.
2. Make sure `PIA Bazzite` is disconnected.
3. Keep this document or the emergency-reset command available.
4. Expect one terminal `sudo` prompt and later one graphical Polkit prompt.

Run:

```bash
cd /home/alex/PIA-Bazzite
bash tools/kill-switch-connection-stage5b-host-test.sh
```

The script installs the exact current helper, then arms an independent root
systemd timer before the production table can be created. The timer destroys
only `inet pia_bazzite_killswitch` after ten minutes if the test cannot cancel
it normally.

The real sequence is:

1. Prove baseline IPv4 access; probe available IPv6 and direct TCP/UDP DNS.
2. Create a private temporary PIA WireGuard configuration.
3. Read its exact numeric endpoint and determine the physical route.
4. Authorize the verified helper session.
5. Enable and structurally verify the production firewall table.
6. Start and verify the real NetworkManager WireGuard profile.
7. Confirm that the public IP changed.
8. Stop and verify the VPN while retaining the firewall.
9. Prove that ordinary IPv4, available IPv6, and available direct DNS paths are
   blocked.
10. Deliberately disable and verify the production table.
11. Confirm that normal IPv4 and public-IP access returned.
12. Cancel the independent reset timer.

A complete pass ends with:

```text
ALL STAGE-5B REAL HOST CONNECTION TESTS PASSED
ALL STAGE-5B REAL HOST TESTS PASSED
```

## Fail-closed behavior

After firewall preparation begins, an uncertain error returns a distinct status
and leaves the independent reset timer armed. The driver tries to stop an
unverified VPN without removing the firewall. It never performs a generic
unlock during exception cleanup.

The terminal then prints the immediate recovery command. The timer remains the
independent fallback even if the Python process, terminal, or helper session
has failed.

## Deliberate emergency reset

Use only when the host test reports that the production firewall may still be
active, or when normal internet remains blocked after the test:

```bash
cd /home/alex/PIA-Bazzite
bash tools/kill-switch-connection-stage5b-emergency-reset.sh
```

This command stops the `PIA Bazzite` VPN profile first, removes only the fixed
production table, stops the Stage-5B reset timer, and verifies that the table is
absent.

## Still deferred

Stage 5B does not yet connect this path to the normal GUI. Reconnect, tunnel
loss, safe server switching, process-crash ownership, startup takeover, and the
final AppImage integration remain later stages.
