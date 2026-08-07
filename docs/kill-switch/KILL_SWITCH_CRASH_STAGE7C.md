# Kill Switch crash takeover Stage 7C

**Status:** Historical integration milestone. Its production behavior is retained, but Stage 7C.4 is the authoritative crash-takeover host proof.


Stage 7C connects the pure Stage-7A verifier and the real Stage-7B crash proof to
normal GUI startup. A restarted app may now adopt a surviving production lock,
but only after the live helper route, NetworkManager profile, and private
recovery record agree exactly.

## Automatic clean-start reconciliation

When the Kill Switch preference is enabled, or when the fixed recovery record
exists, the GUI starts one automatic reconciliation worker. The user no longer
has to press **Schutzstatus neu prüfen** before choosing a server after a clean
external reset.

The worker:

1. loads the private recovery record without following symlinks;
2. opens the restricted authenticated helper session;
3. reads helper and NetworkManager state twice;
4. refuses reconciliation if either snapshot changes;
5. evaluates the stable snapshot with `CrashRecoveryVerifier`.

A clean disconnected host with no table and no record becomes the ordinary
Kill-Switch-ready state. A valid stale record is cleared only after the helper
proves that the production table is absent.

## Exact crash-state adoption

A connected state is adopted only when all of these facts match:

- the production firewall table is present and structurally verified;
- its exact physical-interface and numeric endpoint allowlists equal the record;
- NetworkManager reports the exact saved PIA profile UUID;
- the record passes ownership, permission, schema, route, and checksum checks.

A disconnected state with the same verified table and record is adopted only as
safely blocked. The conservative recovery baseline requires IPv4, IPv6,
DNS-over-TCP, and DNS-over-UDP to be blocked before any later unlock.

After successful adoption, the GUI atomically rewrites the recovery record with
a new process-session ID. This creates an observable takeover boundary without
changing NetworkManager or nftables. Any mismatch remains fail-closed and is
shown as a protection error; the app never removes or weakens the firewall.

## Real Stage-7C host test

`tools/kill-switch-crash-stage7c-host-test.sh` performs the production-host test:

1. starts from no app, VPN, table, or record;
2. verifies that a clean startup automatically retains an authenticated helper
   session without a manual protection-status click;
3. establishes a real protected GUI connection and starts the independent
   physical-path sentinel;
4. kills the exact first GUI process with `SIGKILL`;
5. proves that VPN, firewall, record, and direct-path blocking survive;
6. launches a second GUI and requires exact connected-state adoption;
7. requires the recovery session ID to rotate while route and profile stay
   unchanged;
8. stops the sentinel only after takeover is proven;
9. requires the restarted GUI to perform a normal verified disconnect and clear
   the record;
10. cancels the independent 15-minute reset only after normal connectivity is
    confirmed.

The test never opens or removes the production firewall itself. On any failure
after a lock is observed, it terminates the GUI, exits fail-closed, and leaves
the independent reset armed.
