# PIA Bazzite 0.7.0 release test checklist

The static self-test does not contact PIA and does not change NetworkManager.

1. Run `bash tools/release-unprivileged-gate.sh`; all authoritative unprivileged gates must pass.
2. Start from source and confirm the window title is only `PIA Bazzite`.
3. Confirm DE/EN and System/Light/Dark presentation, including 125% and 150% Plasma scaling.
4. Confirm the compact Main and larger Live-Log window sizes remain fully usable.
5. Confirm location search and the All/Normal/Virtual/Streaming filters combine correctly.
6. Confirm persistent favorites, neutral non-favorite stars, compact virtual/streaming markers, and tray favorites.
7. Confirm the tabbed Options dialog, Save/Cancel behavior, and persisted settings.
8. Connect/disconnect in normal VPN mode; verify Blue connected state, public IP/country, DNS, and IPv6-only guard.
9. Enable Session Kill Switch; verify firewall-first protected connect reaches Green.
10. Force the NetworkManager VPN profile down; verify fail-closed protected recovery returns to Green.
11. Intentionally disconnect with Session Kill Switch enabled; verify VPN-down before firewall release and normal network restoration.
12. Remove and restore the physical Wi-Fi/Ethernet path; verify Green→Orange→Green with Session Kill Switch and Blue→Grey→Blue without it.
13. Test server switching with confirmation enabled and disabled.
14. Test fastest, favorite, fixed normal, virtual, and streaming-filtered location selection.
15. Test public-network provider switching (GeoJS, FreeIPAPI, ipwho.is) and disabling the public IP/location display.
16. Test Auto-Connect Off, Last selected, Fastest/fixed target, and existing-VPN adoption.
17. Test login autostart with tray enabled (tray-first) and tray disabled (Main visible).
18. Confirm closing Main to tray does not emit the old repetitive minimize notification.
19. Confirm a second application start raises the existing instance instead of creating a competing controller.
20. Test the live-log copy, clear, and save actions; inspect shared logs for secrets before posting.
21. On Bazzite, build the release candidate with `PIA_BAZZITE_BUILD_MODE=release ./packaging/build-appimage-podman.sh` from a clean committed tree.
22. Run `APPIMAGE_EXTRACT_AND_RUN=1 ./dist/PIA-Bazzite-0.7.0-x86_64.AppImage --version`.
23. Verify the SHA-256 sidecar and run `bash tools/release-stage8c2-packaging-host-test.sh`.
24. Run the real packaged-helper install/current/outdated host gate when helper packaging changed or before a major release freeze.
25. Integrate the final AppImage with Gear Lever and repeat the release smoke subset from the packaged artifact.

## Stage 8B: packaged AppImage helper install/upgrade gate

Run:

```bash
bash tools/release-stage8b-self-test.sh
```

This gate is unprivileged and network-free. It verifies exact AppImage-to-installed-helper
hash matching, missing/outdated/unsafe classifications, the explicit Polkit install or
upgrade command boundary, post-install re-verification, AppRun bundle discovery, and GUI
gating before first enable or crash-recovery startup. Matching stage/protocol numbers alone
never make an older helper current. See
`docs/release/STAGE8B_PACKAGED_HELPER_INSTALL_UPGRADE.md`.

The real AppImage host gate remains separate and is run only after this self-test passes.


## Stage 8A: 0.7.0 release and AppImage packaging audit

Run:

```bash
bash tools/release-stage8a-self-test.sh
```

This gate is unprivileged and network-free. It verifies that the 0.7.0 version is
consistent across runtime, desktop/AppStream metadata, release notes, workflows, and
the AppImage builder. It also builds the fixed Kill Switch helper payload into a
temporary directory and checks its manifest and hashes. The AppImage now carries the
exact helper installer payload required for Stage 8B; Stage 8B is responsible for the
explicit authenticated install/upgrade flow and the first real AppImage host test.


## Stage 6C.2 emergency-reset reconciliation

If a documented Emergency Reset is executed while the GUI is still open, the GUI
never assumes that the firewall is gone. The main action changes to **Recheck
protection status** when no matching in-memory reconnect baseline exists. The check
uses the fixed installed helper in read-only `status` mode. Only a verified absent
production table clears the stale error and permits normal exit. A present or
unverifiable table remains fail-closed. The real GUI sentinel harness also refuses
to start while another PIA Bazzite instance owns the application socket.

## Stage 7 final release acceptance

Stage 7 is complete. For release acceptance, use these authoritative gates:

```bash
bash tools/kill-switch-crash-stage7d-self-test.sh
bash tools/kill-switch-crash-stage7c4-host-test.sh
bash tools/kill-switch-crash-stage7d-host-test.sh
```

The Stage-7D self-test is the complete unprivileged regression gate. Stage 7C.4 is
the authoritative real crash/restart takeover proof. Stage 7D is the authoritative
adversarial recovery and Emergency Reset proof. The older Stage 7C, 7C.1, 7C.2,
and 7C.3 host harnesses remain in the repository as historical regression and
diagnostic material; they are not release-acceptance gates.

Production hardening discovered during the intermediate runs remains part of the
final implementation: Stage 7C.1's GUI-thread takeover ordering and Stage 7C.3's
live-transport/post-handoff verification are retained. Only the superseded external
process-proof assumptions were replaced by the corrected Stage-7C.4 peer-pipe proof.

See `docs/kill-switch/KILL_SWITCH_CRASH_STAGE7_FINAL.md` for the final invariants,
retained lessons, and release evidence.

## Stage 7A crash-recovery state boundary

Run `./tools/kill-switch-crash-stage7a-self-test.sh`. This unprivileged test verifies
atomic private record storage, strict corruption and symlink rejection, exact
helper allowlist reporting, conservative IPv4/IPv6/DNS recovery probes, and pure
fail-closed adoption decisions. It does not start the GUI or change NetworkManager
or nftables. Real crash and restart/adoption tests remain gated behind Stage 7B/7C.

## Stage 7B: real GUI SIGKILL persistence

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7b-self-test.sh
```

It compiles the project and runs all connection, recovery, crash-state, UI,
client, helper, Polkit, and current release regression tests without touching the host
network.

The real test is intentionally separate:

```bash
bash tools/kill-switch-crash-stage7b-host-test.sh
```

Close every existing PIA Bazzite instance first. The test launches the project
GUI and asks for one protected connection. It then kills that exact GUI process
with `SIGKILL` and independently verifies that the VPN, production firewall,
private recovery record, and direct-path leak sentinel remain safe. Successful
proof is followed by a deliberate VPN-first reset and record cleanup.

For an immediate deliberate reset after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7b-emergency-reset.sh
```

## Stage 7C: automatic startup reconciliation and crash takeover

**Historical integration gate:** retained for regression history; use Stage 7C.4 for final crash-takeover acceptance.

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c-self-test.sh
```

The GUI now performs an automatic authenticated protection-status check when the
Kill Switch preference is enabled or a recovery record exists. A clean host no
longer requires the manual **Recheck protection status** button before server
selection. Existing protection is adopted only after two stable helper and
NetworkManager snapshots exactly match the private record.

The real crash-and-restart test is separate:

```bash
bash tools/kill-switch-crash-stage7c-host-test.sh
```

Close every existing PIA Bazzite instance first. During the first launch,
authenticate the automatic status check but do not press the manual recheck
button. Connect to any server and wait for green protection. The test kills the
exact GUI process, verifies that protection survives, starts a second GUI, and
requires automatic exact takeover with a rotated recovery session ID. After the
restarted app shows green, use its normal disconnect button. Success requires a
verified VPN-first release, absent firewall table, removed recovery record, and
restored normal connectivity.

For an immediate deliberate reset after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c-emergency-reset.sh
```

## Stage 7C.1: retained helper session before takeover commit

**Production hardening retained; original host proof is historical.**

Run the unprivileged ordering gate first:

```bash
bash tools/kill-switch-crash-stage7c1-self-test.sh
```

Stage 7C.1 moves recovery-record clearing and rotation out of the background
worker. The GUI must retain the exact authenticated helper session before a new
recovery session ID can be written. A record-write failure remains fail-closed
and does not close the retained broker or alter VPN/firewall state.

Repeat the real crash takeover with:

```bash
bash tools/kill-switch-crash-stage7c1-host-test.sh
```

The host test requires the rotated record and the restarted GUI's restricted
helper session to remain stable together before it permits the normal GUI
disconnect. For immediate cleanup after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c1-emergency-reset.sh
```

## Stage 7C.2: privileged retained-session process proof

**Historical proof experiment:** its ancestry/cmdline ownership assumptions are superseded by Stage 7C.4.

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c2-self-test.sh
```

Stage 7C.2 keeps the Stage-7C.1 production takeover ordering and corrects the
external process proof. An unprivileged `/proc/<pid>/cmdline` scan cannot always
distinguish a missing helper from a root-owned helper whose command line is not
readable after `pkexec`. The real host test therefore uses its already-authorized
`sudo -n` boundary only for a read-only root-visible process-tree check.

Repeat the real crash takeover with:

```bash
bash tools/kill-switch-crash-stage7c2-host-test.sh
```

Success requires the root-visible restricted helper PID to remain an exact
descendant of the restarted GUI while the rotated record, NetworkManager
profile, firewall route, and independent leak sentinel stay stable together.
For immediate cleanup after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c2-emergency-reset.sh
```

## Stage 7C.3: live transport handoff and pipe-bound ownership proof

**Production liveness/handoff hardening retained; original external discovery proof is superseded by Stage 7C.4.**

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c3-self-test.sh
```

The production session client now treats a cached ready frame as open only while
its actual transport process is alive. Startup takeover additionally performs a
post-handoff read-only status exchange from the GUI thread before rotating the
recovery session ID.

Repeat the real crash takeover with:

```bash
bash tools/kill-switch-crash-stage7c3-host-test.sh
```

The host proof no longer assumes that `pkexec` preserves process ancestry. It
requires exactly one root-visible restricted helper whose three private stdin,
stdout, and stderr pipes are simultaneously held by the restarted GUI. The
helper binding, rotated record, NetworkManager profile, firewall route, and leak
sentinel must remain stable together before normal disconnect is permitted.
For immediate cleanup after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c3-emergency-reset.sh
```

## Stage 7C.4: corrected root peer-pipe proof

**Authoritative real crash/restart takeover release gate.**

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c4-self-test.sh
```

Stage 7C.4 leaves the production takeover logic unchanged and fixes the external
proof used by Stage 7C.3. The privileged probe excludes its own `sudo`/Python
ancestor chain and scans every process sharing a GUI pipe before considering
command-line identity. A valid retained session requires exactly one root-owned
transport whose three distinct stdio pipes are paired with the restarted GUI.

Repeat the real crash takeover with:

```bash
bash tools/kill-switch-crash-stage7c4-host-test.sh
```

The same transport PID, rotated recovery record, NetworkManager profile,
firewall route, and independent leak sentinel must remain stable together. On a
failure, the report includes every process sharing a GUI pipe, including UID,
executable, command line, ancestry, and shared pipe IDs. For immediate cleanup:

```bash
bash tools/kill-switch-crash-stage7c4-emergency-reset.sh
```

## Stage 7D: final adversarial recovery and Emergency Reset gate

**Authoritative final adversarial recovery release gate.**

Run the unprivileged final Stage-7 gate first:

```bash
bash tools/kill-switch-crash-stage7d-self-test.sh
```

This includes the full Stage-5/6 and Stage-7 recovery suite plus the existing UI,
client, helper, Polkit, and current release regression tests. It does not use privilege
escalation or change host networking.

The final real Stage-7 host test is:

```bash
bash tools/kill-switch-crash-stage7d-host-test.sh
```

It first proves that a corrupted private recovery record on a clean host is refused
without privileged/network mutation. It then creates a deliberate verified production
firewall lock with no recovery record and no VPN. The real GUI must refuse ownership
while an independent physical-path sentinel stays blocked and while the exact firewall
route remains unchanged. Finally the test exercises the VPN-first Stage-7D Emergency
Reset and requires a clean automatic GUI restart without the manual **Recheck
protection status** button.

For immediate cleanup after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7d-emergency-reset.sh
```

The Stage-7C.1 production ordering hardening remains final. The Stage-7C.2 and original
Stage-7C.3 external process-proof assumptions are superseded by the successful
Stage-7C.4 peer-pipe proof: `pkexec` ancestry and `/proc` command-line visibility are
not release-quality ownership signals. Keep the older tests as historical regression
material, but use Stage 7C.4 and Stage 7D as the authoritative final Stage-7 host
gates.


### Stage 7D.1: Python 3.14 dynamic-import harness regression

The first Stage-7D host invocation failed before any adversarial host action because the
driver loaded the Stage-7C.4 dataclass module with `exec_module()` before registering it
in `sys.modules`. Stage 7D.1 fixes that Python 3.14 compatibility issue and permanently
smoke-tests the complete Stage-7D import path. This regression belongs to the test
harness; production VPN/firewall behavior was not exercised by the failed run.

### Stage 8B.2 — real 0.7.0 AppImage helper host gate

Run the unprivileged gate first:

```bash
bash tools/release-stage8b2-self-test.sh
```

The real Bazzite host gate builds the Ubuntu-22.04 release-candidate AppImage, verifies its helper bundle, proves that the user-readable AppImage FUSE payload can be copied into the exact private normal-filesystem staging path used for privilege handoff and read there by root, and then exercises missing/current/outdated helper installation states without intentionally connecting the VPN:

```bash
bash tools/release-stage8b2-host-test.sh
```

If the interactive gate fails after deliberately changing the installed helper and the host is otherwise clean, use:

```bash
bash tools/release-stage8b2-emergency-restore.sh
```

If a VPN connection or production Kill Switch table exists, use the Stage-7D Emergency Reset instead of the helper-only restore.
