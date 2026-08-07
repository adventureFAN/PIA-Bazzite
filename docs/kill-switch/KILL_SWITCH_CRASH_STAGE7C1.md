# Kill Switch crash takeover Stage 7C.1

**Status:** Production ordering hardening retained. The original descendant-based host proof is historical; final acceptance uses Stage 7C.4.


Stage 7C proved that the clean-start reconciliation, hard-crash persistence,
record matching, and direct-path blocking were safe. The real test then found a
narrow takeover-ordering defect: the background worker rotated the recovery
session ID before the GUI thread had retained the authenticated helper session.
The host remained fail-closed, but the rotated record could not prove continued
GUI ownership of the broker.

## Retained before record rotation

Stage 7C.1 makes the startup worker verification-only. It loads the private
record, opens the restricted helper session, takes two stable helper and
NetworkManager snapshots, and returns the exact decision without changing the
record.

The GUI-thread commit boundary now follows this order:

1. require the returned helper session to still be open;
2. retain that exact session in `MainWindow._kill_switch_session`;
3. cache the verified helper status;
4. only then clear a proved-stale record or rotate an exactly adopted record;
5. expose the clean, connected, blocked, or refused UI state.

Therefore a changed recovery session ID is no longer evidence that a background
worker merely opened a broker. It is evidence that the live GUI first retained
the broker and then published the takeover commit.

If record clearing or rotation fails, the app keeps the authenticated helper
session, reports a protection error, and remains fail-closed. It does not alter
NetworkManager or nftables.

## Hardened real-host proof

The Stage-7C takeover driver now requires the rotated record and the restarted
GUI's restricted helper descendant to remain stable together. If the record is
rotated without a retained session for ten seconds, the test stops fail-closed
with a specific ordering error. The independent physical-path sentinel remains
active through the whole observation.

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c1-self-test.sh
```

Then run the real host test only after the gate passes:

```bash
bash tools/kill-switch-crash-stage7c1-host-test.sh
```

For an immediate deliberate reset after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c1-emergency-reset.sh
```
