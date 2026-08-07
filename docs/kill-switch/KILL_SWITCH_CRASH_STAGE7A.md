# Kill Switch crash recovery Stage 7A

Stage 7A builds the unprivileged, fail-closed state and reconciliation boundary
needed before the GUI is allowed to adopt protection left behind by a hard crash.
It does not yet integrate adoption into the normal application startup.

## Recovery record

The record contains only:

- a schema and fixed record identity;
- a random session UUID;
- the last protected phase;
- the exact NetworkManager profile UUID;
- the exact physical-interface and numeric-endpoint allowlists.

It is written atomically in the user's state directory with mode `0600`, `fsync`,
and same-directory `os.replace`. Symlinks, non-regular files, foreign ownership,
broad permissions, oversized files, partial JSON, unknown fields, invalid UUIDs,
unsafe routes, and checksum mismatches are rejected.

The checksum detects accidental corruption and partial/manual edits. It is not a
security signature because the record and application run as the same user.
Consequently the record can never prove protection on its own.

## Exact live verification

The helper's read-only status now exposes the normalized contents of the production
firewall's physical-interface and endpoint sets. A restart may adopt a record only
when all independent facts agree:

1. the helper verifies the owned production table and all required rules;
2. the live firewall allowlists exactly match the record;
3. if a VPN is active, NetworkManager reports the exact recorded profile UUID;
4. if the VPN is down, no active profile UUID is accepted.

A verified table without a matching safe record is treated as an unowned lock and
is never adopted automatically. Any mismatch remains fail-closed.

## Conservative post-crash probes

The original pre-firewall reachability baseline cannot be trusted after a hard
crash. Recovery therefore requires IPv4, available or newly available IPv6, direct
DNS over TCP, and direct DNS over UDP all to be blocked before a later deliberate
unlock. This may refuse an unlock unnecessarily, but it cannot omit a path merely
because the crashed process did not persist it.

## Deferred to Stage 7B/7C

Stage 7A does not:

- write records from the real GUI;
- kill the real GUI;
- open or remove firewall rules;
- adopt a record during application startup;
- reconnect or disconnect NetworkManager.

Those actions require separate real-host and GUI tests.
