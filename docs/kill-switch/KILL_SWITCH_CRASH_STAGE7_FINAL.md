# Kill Switch Stage 7 final crash-recovery design

Stage 7 is complete. This document records the final crash/restart behavior, the
security invariants retained from the intermediate stages, and the authoritative
release evidence.

## Final security invariants

1. **A GUI crash never opens the firewall.** The production nftables table is owned
   independently of the GUI process and survives a hard `SIGKILL`.
2. **The recovery record is only a hint.** It cannot authorize VPN or firewall
   mutation by itself. Adoption requires independently verified helper state, the
   exact firewall route, NetworkManager state, and a valid private record to agree.
3. **Unknown ownership stays fail-closed.** A verified production firewall table
   without a matching recovery record is an unowned lock and is never adopted,
   replaced, retargeted, or unlocked automatically.
4. **Takeover is committed only after a live helper handoff.** The GUI retains the
   exact authenticated restricted session, verifies that its real transport is alive,
   performs a post-handoff read-only status exchange, and only then rotates the
   recovery session ID.
5. **Normal startup reconciles automatically.** On a clean released host the app
   clears only a proved-stale valid record and returns to normal server selection
   without requiring the manual protection-status button.
6. **Malformed state is not normalized away during startup.** Unsafe recovery paths,
   malformed records, symlinks, foreign ownership, broad permissions, and schema or
   checksum failures are refused rather than silently trusted or deleted.
7. **Verified-release cleanup is separate from startup.** Only after VPN absence and
   firewall absence are independently verified may the fixed untrusted recovery
   pathname be discarded, without following symlinks and without removing
   directories or special files.
8. **Release remains VPN-first.** Intentional disconnect and Emergency Reset stop and
   verify the PIA VPN before removing the fixed production firewall table.
9. **Uncertainty never becomes green.** Any mismatch or unverifiable state is exposed
   as blocked/error and preserves the lock.

## Retained lessons from Stage 7C.1 through 7C.4

Stage 7C.1 found a real ordering weakness in the takeover commit boundary. Its fix is
part of the final production design: the background worker is verification-only and
the GUI thread retains the authenticated session before publishing a new recovery
session ID.

Stage 7C.2 showed why `/proc/<pid>/cmdline` visibility and a simple `pkexec` process
relationship are not reliable ownership evidence on a hardened Linux host. The
ancestry-based external proof is retained only as historical diagnostic material.

Stage 7C.3 added production hardening that remains final: `KillSwitchSessionClient`
tracks the actual transport process lifetime and startup takeover performs a
post-handoff status exchange before record rotation. Its first external pipe-discovery
probe was still too dependent on process identification and produced a false negative.

Stage 7C.4 corrected the external proof without weakening production behavior. The
root-visible probe excludes its own process family, discovers candidates from the
actual GUI pipe peers instead of helper command-line text, and requires one root-owned
transport paired to all three private stdio pipes. This is the authoritative takeover
proof.

Stage 7D then hardened verified-release cleanup and proved refusal of corrupted
recovery state and an unowned production lock. Stage 7D.1 fixed a Python 3.14 dynamic
module-loading issue in the test harness; it did not change production VPN/firewall
behavior.

## Authoritative release gates

Run the full unprivileged regression gate:

```bash
bash tools/kill-switch-crash-stage7d-self-test.sh
```

The authoritative real-host gates are:

```bash
bash tools/kill-switch-crash-stage7c4-host-test.sh
bash tools/kill-switch-crash-stage7d-host-test.sh
```

Stage 7C.4 proves hard GUI crash, surviving VPN/firewall/recovery state, automatic
restart takeover, retained root session transport, no direct-path fallback, and a
verified normal GUI disconnect. The successful host run observed no direct fallback
across 50 independent sentinel samples.

Stage 7D proves refusal of a corrupted recovery record, refusal to adopt or modify a
verified unowned lock, a continuously blocked physical path, VPN-first Emergency
Reset, verified recovery-path cleanup, and a clean automatic GUI restart without the
manual protection-status button. The successful unowned-lock run observed no direct
fallback across 47 independent sentinel samples.

The Stage 7C, 7C.1, 7C.2, and 7C.3 real-host scripts remain useful historical and
diagnostic artifacts, but they are not final release-acceptance gates.
