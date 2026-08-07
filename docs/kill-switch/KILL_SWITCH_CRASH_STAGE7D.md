# Kill Switch Stage 7D: final adversarial recovery and Emergency Reset gate

**Status:** Authoritative final adversarial recovery and Emergency Reset release gate for Stage 7.


Stage 7D closes the crash-recovery milestone with deliberately hostile local state.
It does not weaken the fail-closed policy to make recovery easier.

## Final recovery rules

The crash-recovery file remains an unprivileged hint only. It never authorizes a
firewall change, VPN start, VPN stop, or automatic unlock. A restarted GUI may adopt
protection only when independently read helper state, NetworkManager state, the exact
firewall route, and the validated private record agree.

A malformed or unsafe recovery record is refused before it can be trusted. Normal
startup never deletes such an entry merely to recover usability. If the host has been
independently proven released, the fixed recovery pathname may then be discarded
without following symlinks. Directories and special files are never removed by this
cleanup boundary.

A verified production firewall table without a recovery record is treated as an
unowned lock. The GUI may retain a read-only authenticated helper session to inspect
it, but it must not fabricate ownership, create a replacement recovery record, start a
VPN, retarget the firewall, or unlock traffic. The documented Emergency Reset is the
recovery path.

## What the real Stage-7D host test proves

`tools/kill-switch-crash-stage7d-host-test.sh` performs two adversarial scenarios.
First, on a clean host, it places a private but corrupted recovery record at the fixed
path and verifies that the GUI refuses it before privilege, VPN, or firewall activity.
Only after the host is independently confirmed clean is the untrusted pathname
removed.

Second, the test creates a real verified production firewall lock with no recovery
record and no VPN. An independent physical-interface sentinel then verifies that
ordinary IPv4/IPv6/DNS fallback remains blocked while the real GUI performs automatic
startup reconciliation and refuses takeover. The GUI must leave the exact firewall
route untouched and must not invent a recovery record.

After that refusal, the Stage-7D Emergency Reset is exercised. It stops the PIA VPN
first, removes only the fixed production nftables table second, verifies both are
absent, and only then discards the fixed crash-recovery pathname. Normal public
connectivity must return. A fresh GUI launch must then reconcile automatically without
the manual **Recheck protection status** button.

## Lessons retained from Stage 7C.1 through 7C.4

Stage 7C.1's production hardening remains part of the final design: the GUI retains
and probes the exact authenticated helper session before rotating the recovery session
ID. Stage 7C.2 and the original Stage 7C.3 external process-proof assumptions are
superseded as release evidence because `/proc` command-line visibility and `pkexec`
process ancestry are not reliable ownership signals. Stage 7C.4's corrected root
peer-pipe proof is the authoritative crash-takeover proof: it excludes the probe's own
process family and verifies the three private transport pipe peers directly.

The failed intermediate host tests are intentionally preserved as historical
regression material and documentation of assumptions that must not be reintroduced.
They are not the final release gate.

## Commands

Unprivileged final gate:

```bash
bash tools/kill-switch-crash-stage7d-self-test.sh
```

Real adversarial host test:

```bash
bash tools/kill-switch-crash-stage7d-host-test.sh
```

Immediate deliberate recovery after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7d-emergency-reset.sh
```


## Stage 7D.1 harness compatibility note

The first real Stage-7D host run stopped before adversarial host actions on Python 3.14.
The Stage-7D driver dynamically loaded the Stage-7C.4 driver without first registering
the module in `sys.modules`. Python 3.14 `dataclasses` requires that registration while
processing slotted dataclasses. The loader now registers the fixed-name module before
`exec_module`, restores the previous entry on failure, and has a regression smoke test
that imports the complete Stage-7D driver without privileged or network actions.
This was a test-harness failure, not a production kill-switch or fail-closed failure.
