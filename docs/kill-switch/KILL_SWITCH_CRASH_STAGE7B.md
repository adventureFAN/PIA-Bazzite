# Kill Switch crash persistence Stage 7B

Stage 7B connects the Stage-7A recovery record to verified GUI protection and
adds the first real hard-crash test. It deliberately stops before normal startup
adoption; that remains Stage 7C.

## GUI persistence boundary

The GUI owns one fixed journal at:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/pia-bazzite/kill-switch-crash-recovery-v1.json
```

The journal is written only after a protected transition has returned all of the
following as verified:

- the NetworkManager profile UUID;
- the active production firewall table;
- the exact physical-interface allowlist;
- the exact numeric WireGuard endpoint allowlist.

A successful protected connect, reconnect, or server switch writes the
`protected-connected` phase before the operation is reported as successful. An
unexpected tunnel loss updates the hint to `protected-blocking`. A verified
intentional disconnect, verified Kill-Switch disable, or read-only proof that an
external emergency reset removed the table clears the record.

A persistence failure never opens the firewall. If the VPN is still active after
such a failure, the combined state is treated as requiring attention rather than
being silently reported as fully recovered.

## Real SIGKILL test

`tools/kill-switch-crash-stage7b-host-test.sh` performs the first production-host
crash test:

1. refuses an existing GUI, VPN profile, firewall table, or unsafe stale record;
2. installs the verified helper and arms an independent 15-minute reset;
3. proves a direct physical-path baseline;
4. launches the real project GUI;
5. waits for exact agreement between NetworkManager, nftables, and the private
   recovery record;
6. starts the independent `SO_BINDTODEVICE` leak sentinel;
7. sends `SIGKILL` to the exact GUI PID;
8. verifies that the same VPN profile, exact firewall route, recovery record,
   and blocked physical path survive the dead GUI process;
9. performs deliberate cleanup only after the persistence proof succeeds.

The driver never disables or destroys the production firewall table. On any
post-lock failure it kills the GUI where necessary, exits fail-closed, and leaves
the independent reset armed.

## Deliberately deferred to Stage 7C

Stage 7B does not let a newly started GUI adopt the surviving lock. A normal app
restart still treats the existing table conservatively. Stage 7C will add startup
reconciliation and will require the exact Stage-7A verifier decision before
restoring green or orange runtime state.
