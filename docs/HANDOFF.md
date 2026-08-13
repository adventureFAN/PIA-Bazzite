# PIA Bazzite - Living HANDOFF

**Purpose:** Continuity document for future ChatGPT conversations and later PIA Bazzite development.
**Last updated:** 2026-08-13
**Current public stable release:** **PIA Bazzite 0.6.0**
**Current development baseline:** **0.7.0 development — Stage 1 verified; Stage 2 server favorites fully verified; Stage 3A–3D verified; Stage 4A Auto-Connect Options foundation verified; Stage 4B Auto-Connect startup execution verified and frozen; Stage 4C login-autostart/tray polish verified and frozen**
**Stable release tag:** `v0.6.0`
**Stable release commit:** `4df051f` (`feat: prepare PIA Bazzite 0.6.0 release`)
**Repository:** https://github.com/adventureFAN/PIA-Bazzite
**License:** MIT

> This document is intentionally more detailed than a normal README. It records architecture, security invariants, verified behavior, historical traps, release procedure, and working agreements so a new development chat does not have to reconstruct the project from old conversations.

---

## 1. Project in one paragraph

PIA Bazzite is an unofficial desktop client for Private Internet Access on Bazzite Linux. It creates native PIA WireGuard connections through NetworkManager, loads and measures PIA regions, provides a DE/EN Qt GUI and system-tray workflow, stores credentials through the Linux Secret Service keyring, and implements two separate firewall protections: a narrow IPv6-only guard for ordinary VPN connections and an optional fail-closed Session Kill Switch for IPv4, IPv6, and direct DNS paths. The application is distributed as an AppImage and deliberately keeps the GUI unprivileged; privileged `nftables` work is confined to a fixed, root-owned, checksummed helper installed through explicit user authorization.

PIA Bazzite is unofficial, not affiliated with Private Internet Access, and not endorsed by the Bazzite project.

---

## 2. Current release state

PIA Bazzite **0.6.0 is publicly released on GitHub**.

Release facts:

- Publication date: **2026-08-08**.
- Main release tag: `v0.6.0`.
- Tagged release commit: `4df051f`.
- Expected public assets:
  - `PIA-Bazzite-0.6.0-x86_64.AppImage`
  - `PIA-Bazzite-0.6.0-x86_64.AppImage.sha256`
- The final release workflow builds from the exact tag commit, checks tag/version consistency, runs the release gate, builds/smoke-tests the AppImage, verifies the checksum sidecar, and publishes the GitHub Release.
- The final 0.6.0 RC matrix passed on real Bazzite through blocks 1-19, including normal VPN, IPv6 containment, Session Kill Switch, protected reconnect/server switch, crash recovery, integrated reset, tray/exit behavior, settings persistence, single-instance behavior, suspend/resume, physical-network loss, external NetworkManager disconnect/recovery, Polkit cancellation, offline start/manual recovery, and final UI sanity.
- No fail-open was observed in the final RC testing.
- A post-release independent review found no release-blocking functional or security defect. It produced one documentation clarification about the Session Kill Switch reboot boundary and one checksum/import concern that was resolved by re-checking the real production bootstrap path.

### Post-release 0.6.0 documentation maintenance

The README should prominently state the **Kill Switch scope**:

- tunnel loss or GUI failure while the system/kernel remains running can stay fail-closed because the active `nftables` rules remain in kernel state;
- a full reboot, kernel crash, or power loss clears that runtime firewall state;
- PIA Bazzite is therefore **not** an early-boot firewall, and Kill Switch protection is not active again after boot until PIA Bazzite runs and activates it.

This clarification does not justify a 0.6.1 by itself. Accumulate real bugs/hardening changes and create a maintenance release when there is enough reason.

---

## 3. Source of truth

For future development:

- The **current GitHub `main` branch / a fresh archive from the actual current local checkout** is the source of truth for exact current code.
- The **`v0.6.0` tag at `4df051f`** is the source of truth for the runtime code that shipped as 0.6.0.
- `main` may legitimately move beyond the release tag for documentation-only or later maintenance commits. Always inspect the actual current checkout before changing code.
- This HANDOFF explains intent, architecture, verified behavior and history. It is **not** a substitute for inspecting the current source tree.
- Do not reconstruct a future patch from old A9/A10/A11/A12/A13/A14/stage archives or fragments from previous chats. Those are historical snapshots and may predate later security, recovery, packaging or UI fixes.
- Before a substantial code change, request/inspect the complete current source if it is not already available in the conversation.

This mirrors the working rule proven useful in TrainerBridge: handoff for intent/history, current source for exact implementation.

---

## 4. Development working agreement

The project owner is **adventureFAN**. PIA Bazzite was developed collaboratively with ChatGPT by OpenAI. Maintained public credit wording is:

`Project direction, feature design, testing, and release decisions: **adventureFAN**`

`Most implementation, debugging, and technical documentation: developed collaboratively with **ChatGPT**`

AppStream's formal developer field remains `adventureFAN`.

For future work:

- **Do not patch first and inspect later.** Reconcile the current complete source tree with this HANDOFF before proposing substantial code changes.
- Prefer **one targeted regression test too many rather than one too few**, especially around privilege boundaries, NetworkManager, routing, firewall release, crash recovery and packaging.
- Do not make speculative changes to working security-sensitive code merely because another design looks theoretically cleaner.
- Fix the smallest proven problem. Avoid broad refactors immediately before a security-sensitive maintenance release.
- Treat the project owner as a development beginner for hands-on instructions: give copy/paste-ready commands, explicit paths, explain what each step is doing, and state the expected PASS/output or visible behavior. Do not assume Git, venv, build, Polkit or packaging commands are remembered.
- Prefer complete replacement files or a small patch/archive over asking the user to manually edit Python.
- After changing security-sensitive production logic, rerun the appropriate real-host test; a container/unit test is not sufficient authority for a real networking/firewall behavior change.
- Preserve privacy in public source and release artifacts: no local usernames, personal home paths, credentials, PIA tokens, WireGuard private keys, or accidental development leftovers.
- Public GitHub documentation is maintained in **English**. The application itself remains localized in **English and German**.
- Maintain this HANDOFF after meaningful architecture changes, security decisions, verified host-test results, release-state changes and roadmap decisions. Do not wait until a chat is nearly full.
- After 0.6.0, changes should be driven by real bugs, security/hardening findings or clearly useful user requests. Do not invent features merely to justify a new version number.

---

## 5. Security architecture and invariants

These are release-critical and must not be casually weakened.

1. The optional Session Kill Switch is **fail-closed while the current system session is running**.
2. The full Kill Switch firewall must be established and independently verified **before** a protected VPN is allowed to start.
3. Firewall release is allowed only after PIA VPN absence and the expected safe state have been independently verified.
4. `unknown` NetworkManager state is never treated as `disconnected`.
5. Protected reconnect and protected server switch must never create a direct-network fallback window.
6. The GUI stays unprivileged. Privileged `nftables` work is confined to the fixed installed helper boundary.
7. Packaged helper installation/update must install exactly the verified AppImage payload. Packaged mode must never silently downgrade to source-tree helper mode.
8. The installed helper launcher/bootstrap verifies the fixed root-owned installation and checksum manifest **before importing the installed helper package**. Preserve this pre-import bootstrap boundary.
9. Crash-recovery records are hints, not authority. Adoption requires live helper, NetworkManager, route, firewall and recovery state to agree.
10. The small normal-mode IPv6 guard and the full Session Kill Switch are separate tables and must not be confused or accidentally coexist as competing ownership states.
11. The integrated reset is VPN-first: stop/verify the VPN, keep the Kill Switch active during that verification, remove only PIA Bazzite's fixed Kill Switch table, verify it absent, then clean recovery state.
12. If any reset/release verification is ambiguous or fails, remain fail-closed and do not claim normal networking has been safely restored.
13. Secrets - passwords, PIA tokens, WireGuard private keys - must never enter Live Log, test reports intended for sharing, source archives or release artifacts.
14. The Session Kill Switch is **not boot-persistent**. A full reboot/kernel crash/power loss clears runtime `nftables` state; do not claim otherwise.

### Installed-helper checksum boundary

A post-release review noted that `installed_entry.py` itself has package imports before its local `verify_installation()` call. This is not the production entry boundary. The fixed installed launcher `helper/pia-bazzite-kill-switch-helper-installed` uses only the standard library, verifies the root-owned installation and checksum manifest first, and only then imports `pia_bazzite_kill_switch_helper.installed_entry`. The regression test `tests/polkit/test_installed_helper.py::InstalledFilesStaticTests::test_launcher_verifies_before_importing_installed_package` exists specifically to preserve this ordering.

---

## 6. User-visible connection/protection states

The color semantics are deliberate:

- **Neutral gray:** VPN intentionally disconnected. Kill Switch may be off or merely armed for the next connection.
- **Blue:** VPN connected without the full Session Kill Switch. The narrow IPv6-only guard is active so native IPv6 cannot bypass the PIA IPv4 WireGuard path.
- **Green:** VPN connected and the full Session Kill Switch is active and verified.
- **Orange:** VPN unavailable/down while the verified Session Kill Switch remains active and blocks normal networking safely.
- **Red:** protection is expected but cannot currently be guaranteed/verified.

Do not redefine Green as an internet-reachability heartbeat. During complete physical-network loss, NetworkManager may still report the WireGuard profile administratively active while no handshake can occur. If the full Kill Switch remains verified active, fail-closed traffic blocking is the security property that matters. Do not add a fragile HTTP/ping heartbeat merely to make Green mean “the public Internet answered this second.”

The German manual read-only status action is **`Schutzstatus neu prüfen`**.

---

## 7. Normal VPN versus Session Kill Switch

### Normal VPN, Kill Switch OFF

PIA's WireGuard parameters used by this client provide an IPv4 tunnel/default route but no routed IPv6 `AllowedIPs` path. PIA Bazzite therefore does **not** invent an unsupported IPv6 tunnel route.

Instead:

1. the dedicated helper-owned table `pia_bazzite_ipv6_guard` is enabled and verified before the normal VPN is reported usable;
2. IPv4 uses the PIA WireGuard interface `piabazzite`;
3. native public IPv6 is blocked while the VPN is active;
4. on a verified intentional VPN disconnect, the IPv6 guard is removed and the machine's normal IPv6 connectivity returns.

This narrow guard is **not** a full Kill Switch. If the ordinary VPN disappears unexpectedly with Kill Switch OFF, IPv4 is allowed to return normally after the appropriate state handling; the feature's job is only to prevent simultaneous native IPv6 bypass while the VPN is active.

### Session Kill Switch ON

The full helper-owned `pia_bazzite_killswitch` table is authoritative for fail-closed protection. It allows only the required local/DHCP/link-local traffic, the exact current PIA WireGuard endpoint on the physical interface, and the PIA tunnel path; normal traffic outside the tunnel is rejected.

The small IPv6 guard must not be treated as the full Kill Switch. The two mechanisms have separate state/verification contracts.

### Physical-network loss

When Wi-Fi/underlay disappears, WireGuard can remain administratively `connected` in NetworkManager even though no new handshake is possible. Real testing showed the Kill Switch remained active and both IPv4 and IPv6 were unreachable until the physical network returned. Do not treat this as a fail-open merely because the GUI remained Green.

### KDE/Bazzite “Limited connectivity”

While the full Kill Switch is active, KDE/NetworkManager may report **Limited connectivity** because NetworkManager's own direct connectivity probe cannot bypass the VPN/firewall through the physical interface. This does not by itself mean the PIA tunnel is down. After intentional release, the desktop indicator may remain limited briefly until NetworkManager performs its next check.

---

## 8. Recovery and reset behavior

### Unexpected VPN loss with Kill Switch active

The intended order is:

1. detect VPN loss;
2. retain/verify the existing firewall lock;
3. update crash-recovery state to protected-blocking;
4. verify previously reachable normal IPv4/IPv6/direct-DNS paths are blocked;
5. update endpoint exceptions while the lock remains active;
6. verify the exact protected route;
7. rebuild the NetworkManager WireGuard profile under protection;
8. jointly verify VPN + still-active firewall;
9. save verified crash state and return to Green.

### GUI crash while protected

Because the firewall lives in kernel state, killing only the GUI must not remove protection. On restart the new GUI may briefly show Red/unverified before Polkit authorization because it must not claim protection until the privileged state is checked. After exact verification it can adopt either:

- connected + firewall -> Green; or
- VPN down + exact firewall -> Orange / Safely blocked.

Initial server-list network refresh must remain deferred while a blocking startup recovery is awaiting privileged reconciliation. This prevents an offline modal network error from racing/obscuring Polkit.

### Reset Kill Switch Protection

The user-facing product action is **`Reset Kill Switch Protection…`** / **`Kill-Switch-Schutz zurücksetzen…`**. Internal function/module names may still use `emergency_reset`.

The action is deliberately contextual: hidden during ordinary Gray/Blue/healthy Green states and surfaced only when a known PIA Bazzite Kill Switch firewall makes the recovery action relevant, including safely blocked or certain protection-error states.

After a successful reset, normal networking is restored **without VPN protection** and the user's real public IP may be visible. Never promise continued VPN/IP protection after the reset has deliberately released the firewall.

A genuine startup-recovery failure should offer a direct retry plus the same explicit reset path; reset must never run automatically.

---

## 9. Startup, authorization and single-instance rules

- A remembered Kill Switch preference while the VPN is cleanly disconnected is only an **armed preference**, not proof that a firewall is active.
- Normal disconnected startup with Kill Switch remembered ON must not require Polkit and must not show an unnecessary Red state.
- Quitting from that same clean disconnected/armed-only state must also remain Polkit-free. `request_quit()` should use the existing `_disconnected_kill_switch_may_block()` recovery gate instead of treating an unqueried helper status (`None`) as evidence that a firewall may exist. Real/ambiguous recovery hints still require the privileged status recheck before exit.
- Explicitly disabling the Kill Switch preference remains different: it intentionally verifies privileged host firewall state before changing the protection preference, so an authorization prompt there is acceptable.
- Enabling Kill Switch from OFF may request Polkit so the restricted privileged boundary can be checked/prepared.
- A protected connect can require authorization. If the user cancels Polkit before privileged mutation, the VPN must not start and no half-created firewall may remain.
- Deliberate Polkit cancellation in these pre-mutation paths is a neutral user cancellation/authorization-not-granted outcome, not a catastrophic application error.
- Real crash-recovery reconciliation with a surviving privileged firewall legitimately requires authorization before the new GUI can verify/adopt it.
- PIA Bazzite is single-instance. A second launch must not create a second independent VPN/firewall controller or duplicate tray session.

---

## 10. Persistent paths and installed component

Typical development checkout:

```text
~/PIA-Bazzite
```

XDG user data used by the application:

```text
~/.config/pia-bazzite/settings.ini
~/.cache/pia-bazzite/regions.json
~/.local/state/pia-bazzite/
~/.local/state/pia-bazzite/kill-switch-crash-recovery-v1.json
```

Credentials are stored through the Linux Secret Service/keyring rather than plain-text project files.

The packaged privileged component is installed under the fixed root-owned path:

```text
/usr/local/libexec/pia-bazzite/
```

Production firewall tables:

```text
inet pia_bazzite_ipv6_guard
inet pia_bazzite_killswitch
```

Do not generalize helper operations to arbitrary user-supplied paths/table names. The narrow fixed boundary is intentional.

---

## 11. Important source files

Top-level/runtime:

- `main.py` - application entry point.
- `pia_bazzite/gui.py` - main Qt GUI/controller, tray integration and user workflows.
- `pia_bazzite/settings.py` - XDG paths and persistent settings.
- `pia_bazzite/i18n.py` + `pia_bazzite/resources/i18n/*.json` - DE/EN localization; keep PySide6 imports lazy enough for non-GUI security tests.
- `pia_bazzite/credentials.py` - Secret Service/keyring credential storage.
- `pia_bazzite/pia_api.py` - PIA API/server-list interactions and validated response handling.
- `pia_bazzite/network_manager.py` - fixed PIA NetworkManager/WireGuard profile handling and verified connection state.
- `pia_bazzite/host_open.py` - host desktop opening from packaged environment.
- `pia_bazzite/single_instance.py` - one-controller startup serialization.

Protection/orchestration:

- `pia_bazzite/kill_switch_client.py` - restricted helper client.
- `pia_bazzite/kill_switch_session.py` - authenticated helper session/broker lifecycle.
- `pia_bazzite/kill_switch_connection.py` - protected connect/switch/disconnect ordering.
- `pia_bazzite/kill_switch_recovery.py` - verified recovery decisions and adoption.
- `pia_bazzite/kill_switch_crash_state.py` - persistent recovery journal/markers; hints, not authority.
- `pia_bazzite/kill_switch_runtime.py` / `kill_switch_state.py` - runtime state model.
- `pia_bazzite/network_paths.py` / `network_probes.py` - physical/blocked-path verification.
- `pia_bazzite/ipv6_guard_lifecycle.py` - normal-VPN IPv6-only guard lifecycle.
- `pia_bazzite/emergency_reset.py` - unprivileged VPN-first reset coordinator.

Privileged helper:

- `helper/pia-bazzite-kill-switch-helper-installed` - production pre-import verification bootstrap.
- `helper/pia-bazzite-kill-switch-session-installed` - installed session broker entry.
- `helper/pia_bazzite_kill_switch_helper/core.py` - fixed privileged firewall logic.
- `helper/pia_bazzite_kill_switch_helper/protocol.py` - restricted protocol.
- `helper/pia_bazzite_kill_switch_helper/runner.py`, `cli.py`, `session_entry.py`, `installed_entry.py` - fixed helper/session execution path.

Packaging/release:

- `packaging/build-appimage-podman.sh` - preferred isolated Bazzite/Fedora build path.
- `packaging/build-appimage.sh` - AppImage build logic.
- `packaging/build-helper-bundle.py` - exact helper payload/manifest construction.
- `packaging/collect_third_party_licenses.py` - bundled dependency notice/license collection.
- `packaging/appimage/PIA-Bazzite.spec` - PyInstaller specification.
- `.github/workflows/ci.yml` - public CI gate.
- `.github/workflows/release.yml` - tag-driven release build/publish workflow.
- `tools/release-unprivileged-gate.sh` - common release gate.
- `tools/release-stage8c2-self-test.sh` - authoritative accumulated unprivileged regression gate for the 0.6.0 architecture.
- `tools/release-stage8c2-packaging-host-test.sh` - real packaging/release-hygiene host gate.

Documentation/evidence:

- `README.md`
- `SECURITY.md`
- `TESTING.md`
- `CHANGELOG.md`
- `RELEASE_NOTES_0.6.0.md`
- `THIRD_PARTY_NOTICES.md`
- `docs/HANDOFF.md`
- `docs/kill-switch/` - detailed staged Kill Switch design/test history.
- `docs/release/` - release packaging/helper handoff material.

---

## 12. Deliberate UX and privacy decisions

Do not casually revert these:

- Tray color semantics are Gray / Blue / Green / Orange / Red as documented above.
- Closing the window with tray enabled hides to tray; it does not silently tear down VPN/firewall state.
- With tray disabled, closing the window follows the configured real exit policy. Leaving the VPN connected is refused when doing so would abandon an active Kill Switch protection state.
- The Session Kill Switch preference remains enabled after a successful reset; the next protected connection should use it again.
- Public IP/country lookup uses `api.country.is`. While verified disconnected, it is **not queried automatically**; the user can explicitly request it. Automatic lookups are limited to verified VPN-connected states.
- Offline startup may fail to load the PIA server list. In 0.6.0 there is deliberately no new automatic network-state watcher solely to reload it when Wi-Fi returns; **Refresh server list** is the accepted recovery path.
- Live Log uses compact timestamps and meaningful `OK`, `INFO`, `WARNING`, `ERROR` events; do not add noisy per-poll spam. Secrets must be redacted and public IP display/logging uses masking where designed.
- Long explanatory tooltips should be deliberately wrapped rather than rendered as monitor-wide single lines.
- Public GitHub docs are English-only; runtime UI is DE/EN.
- Do not claim PIA as a service universally lacks IPv6. The precise statement is that the WireGuard parameters currently provisioned to **this client** provide the IPv4 route but no tunneled IPv6 `AllowedIPs` path, so PIA Bazzite blocks native IPv6 while connected.

---

## 13. Known limitations / non-bugs

These are important user expectations, not hidden defects:

- The Session Kill Switch is **not persistent across reboot/kernel crash/power loss**.
- PIA Bazzite is not an early-boot firewall.
- KDE/NetworkManager may show `Limited connectivity` while the full Kill Switch intentionally blocks direct connectivity probes.
- Complete physical-network loss can leave the WireGuard profile administratively active/Green even while no public traffic is possible; the verified firewall still blocks fallback.
- Normal VPN mode blocks native IPv6 rather than tunneling it because the PIA parameters used by this client do not provide a tunneled IPv6 route.
- 0.6.0 does not provide split tunneling, port forwarding, trusted-network rules or automatic connection at login.
- Support is intentionally focused on Bazzite; do not silently broaden support guarantees to arbitrary distributions without testing.

---

## 14. Release smoke/regression checklist

Before a future release, choose scope based on risk. A docs-only change does not require rebuilding the VPN stack. A networking/helper/firewall change does.

### Minimum release sanity

- clean source tree / expected version;
- `bash tools/release-stage8c2-self-test.sh` green;
- packaging host gate green when release/package behavior changed;
- AppImage starts normally and About/version is correct;
- DE/EN and System/Light/Dark basic UI smoke;
- single-instance behavior;
- normal disconnected startup with remembered Kill Switch does not request unnecessary Polkit;
- one normal connect/disconnect cycle;
- public IP shows PIA while connected;
- normal VPN has the IPv6-only guard and no native IPv6 leak;
- intentional disconnect removes the guard and restores normal IPv4/IPv6.

### Critical Session Kill Switch regression subset

For any change touching NetworkManager, helper, firewall, Polkit, recovery or crash-state logic, at minimum re-check:

1. protected connect: firewall verified before VPN start -> Green;
2. protected intentional disconnect: VPN verified down before firewall release -> normal networking restored;
3. forced VPN loss: Orange/fail-closed -> protected reconnect -> Green;
4. protected server switch: old tunnel stops under lock, endpoint exception retargets under lock, new tunnel verifies -> Green;
5. GUI crash while protected connected: firewall/VPN survive -> restart exact adoption -> Green;
6. GUI crash while protected-blocking: restart exact adoption -> Orange -> protected reconnect -> Green;
7. integrated Reset Kill Switch Protection from a deliberately blocked/error state: VPN down verified -> fixed table removed/verified -> normal IPv4/IPv6 restored;
8. Polkit cancellation before privileged mutation leaves no half-created VPN/firewall state;
9. no secrets in logs or generated release evidence.

### Previously completed 0.6.0 real-host RC matrix

The final 0.6.0 cycle also verified first-run helper installation/update UX, normal server switching, tray behavior, exit policies, settings persistence, tray-disabled shutdown, suspend/resume, physical Wi-Fi loss/recovery, external NetworkManager VPN disconnect/recovery, offline start/manual server-list refresh, links/About/log actions and final normal protected use. Do not repeat every adversarial test for a tiny unrelated patch, but do not skip the changed area plus critical safety paths.

---

## 15. Release / GitHub procedure

For 0.6.0 the successful publication flow was:

1. freeze the exact tested source;
2. commit it on `main` and require a clean working tree;
3. push `main`;
4. wait for CI to be green on that exact commit;
5. create annotated tag `v0.6.0` on the same commit;
6. verify tag commit equals tested `main` commit;
7. push the tag;
8. let the pinned GitHub release workflow build from that exact tag commit;
9. verify the release contains the versioned AppImage and `.sha256` sidecar;
10. perform a final checksum/version smoke check on the published asset.

For future releases, preserve the same principle: **tag exactly what was tested; build the public artifact from exactly what was tagged.** Never retag a different commit under the same public version.

The release workflow has `contents: write`, so third-party GitHub Actions used in CI/release were pinned to exact reviewed commit SHAs during the 0.6.0 freeze. Do not casually revert those to floating major tags.

GitHub-provided source archives should come from the tagged commit; do not create an unrelated hand-packed source archive as the public source of truth unless there is a specific reason.

---

## 16. Planned future development stance

The original 0.6.0 goal is complete. There is no requirement to create 0.6.1 or 0.7.0 merely because time has passed.

Preferred approach:

1. use PIA Bazzite normally;
2. collect real annoyances/bugs and security/hardening findings;
3. accept useful GitHub reports;
4. group meaningful maintenance work into 0.6.1 when justified;
5. reserve larger behavior/features for later minor versions and give security-sensitive features dedicated design/testing.

Current candidate roadmap, not promises:

### 0.7.0 development approach

0.7.0 is intentionally being built in small, separately testable stages rather than as one large feature drop. Each bug fix or feature should have a narrow goal, focused regression coverage, a real-host/UI proof when relevant, a HANDOFF update, and a clean commit before the next stage begins.

**Stage 1 complete — clean-idle quit UX (2026-08-12):**

- Real-use finding: after more than a week of normal use, quitting PIA Bazzite immediately after startup could request administrator authorization when the Session Kill Switch preference was remembered ON, even though no VPN connection had been started in that process and no recovery hint existed.
- Cause: `request_quit()` treated `_kill_switch_status is None` as “the firewall may be active”. A fresh armed-only startup deliberately keeps that status unknown because A13 removed unnecessary startup Polkit; therefore the quit path accidentally reintroduced the prompt.
- Implemented fix: `request_quit()` reuses `_disconnected_kill_switch_may_block(connected=False)`. With no live VPN, no cached firewall/error, no crash record and no reconciliation marker, quitting is immediate and unprivileged. If any real/ambiguous protection hint exists, the existing privileged read-only recheck remains mandatory before exit.
- Scope is deliberately narrow: **do not change the explicit Kill Switch disable path**. Turning the preference off may still request authorization so actual host firewall state can be verified before protection is changed.
- Focused regression coverage lives in `tests/connection/test_idle_quit.py`; `tools/0.7-stage1-idle-quit-self-test.sh` runs it together with the relevant A13/crash-recovery quit tests without touching Polkit, NetworkManager, nftables or the real GUI.
- Verification completed on real Bazzite: with the Kill Switch preference remembered ON, a clean app start followed by Quit without ever connecting exits without a Polkit/admin-password prompt. A separate connected VPN + Kill Switch exit still shows the existing quit confirmation and follows the protected disconnect/quit path; no unnecessary second Polkit prompt appeared because the already-authorized helper session remained available. The focused Stage 1 self-test also passed together with the relevant A13/crash-recovery/static regression suites, including coverage that real or ambiguous blocking/recovery hints still require the existing protected recheck and that explicitly disabling the Kill Switch still checks privileged host state. Treat Stage 1 as verified.

**Stage 2A verified — persistent server-favorites core (2026-08-12):**

- Server favorites are deliberately user-owned state. PIA Bazzite may update the saved display fallback for a favorite when that same `region_id` appears in a later successful PIA catalog, but it must **never automatically delete a favorite merely because the region disappears from a refresh**.
- The feature limit is **10 favorites**. Missing/unavailable favorites continue counting toward that limit until the user explicitly removes them; removing an unavailable favorite immediately frees a slot.
- Persistence lives behind `FavoriteRegionStore` in `pia_bazzite/region_favorites.py`. Each favorite stores only `region_id`, the last known PIA `name`, and the `geo` flag. Stale endpoint IP/hostname/ping data is intentionally not persisted as favorite state and must never be used to connect to a region that is absent from the current catalog.
- “Unavailable” means **absent from the current successfully loaded PIA region catalog**, not “latency probe failed”. A catalogued region with `ping_ms is None` remains an available region and keeps the existing “not reachable” semantics.
- The core exposes availability as a current `Region` object or `None`. This is the safety boundary for later UI work: an unavailable favorite can be shown and removed, but cannot provide stale connection endpoint data.
- Stage 2B main-window requirement: only unavailable **favorites** may remain visible as retained/disabled rows. A non-favorite region that PIA no longer supplies must not be kept as a gray zombie row. The unavailable row itself must not be connectable, while its favorite control must remain usable so the user can remove it.
- Stage 2C tray behavior: favorites belong in their own **root-level `Favorites` submenu beside** the existing `Connect to…` / `Switch server…` submenu, before the separator that leads to Show/Quit. The Favorites submenu is absent when no favorites are saved. The normal Connect/Switch server submenu remains unchanged. Unavailable favorites remain visible but disabled/non-connectable inside Favorites. All available favorite actions must reuse the existing `connect_region()` path rather than create separate VPN/server-switch logic.
- Focused regression coverage lives in `tests/connection/test_region_favorites.py`; `tools/0.7-stage2a-server-favorites-core-self-test.sh` runs the 13 core tests plus the existing release self-test without contacting PIA or mutating real settings/network/firewall/GUI state. The complete Stage 2A self-test passed in the real development checkout on Bazzite, including all 13 focused favorites-core tests and the existing release self-test. Because Stage 2A intentionally has no GUI, PIA-network, helper, firewall, or NetworkManager integration yet, this non-mutating checkout verification is the required acceptance proof. Treat Stage 2A as verified.

**Stage 2B verified — main-window server-favorites UI (2026-08-12):**

- `RegionComboBox` keeps the normal Qt combo/list selection path but intercepts only the small star hit target in the popup. Star press/release events are consumed and routed through a dedicated `favoriteToggled(region_id)` signal, so toggling a favorite must not emit the normal server-selection action or trigger an accidental server switch while already connected.
- Available region rows use a dedicated leading marker icon: active `★` favorites and the Fastest lightning marker use the same yellow/gold accent treatment, while inactive `☆` stars follow the current theme text color. The server name itself stays in the normal theme text color. Real Bazzite visual testing showed that drawing the Unicode `⚡` glyph into a `QPixmap` with the combo's UI font can produce a blank icon even though the same character renders correctly in KDE tray action text. The Fastest marker therefore uses a small font-independent `QPainterPath` vector bolt; do not regress it back to font-glyph rendering. Retained unavailable favorites remain disabled/gray as a row while their star hit target stays removable. Favorites are grouped first, then retained unavailable favorites, then the existing Fastest entry (when no search filter is active), then the remaining normal regions. Available favorites retain the current PIA catalog/ping ordering rather than inventing a second manual order. The combo popup must always call `scrollToTop()` after Qt opens/resizes it; otherwise Qt scrolls around the currently selected region and can make the list appear to start in the middle instead of showing the intended favorites → Fastest → normal ordering from the top.
- A favorite absent from the currently loaded catalog is reconstructed only from its safe stored identity/display snapshot and rendered as `Not available` / `Nicht verfügbar`. The row is disabled for normal selection/connection, but the popup event filter still allows the star hit target so the user can remove it. No stale endpoint IP/hostname is created or passed to `connect_region()`.
- Regions absent from the PIA catalog and not favorited are not synthesized into the combo at all. A catalogued region with `ping_ms is None` remains an ordinary selectable row with the existing `not reachable` text; failed latency measurement is not treated as catalog disappearance.
- Successful full catalog refresh calls `FavoriteRegionStore.refresh_snapshots()` so last-known name/geo fallback metadata stays current for favorites that still exist. Ping-only refresh does not reinterpret catalog membership.
- The 10-item limit remains enforced by the core. Attempting to add an eleventh favorite produces neutral DE/EN informational copy and does not alter the existing ten.
- Focused non-GUI regression coverage is `tests/ui/test_server_favorites_stage2b.py`; `tools/0.7-stage2b-server-favorites-ui-self-test.sh` runs the Stage 2A core tests, Stage 2B source/translation checks, and the existing release self-test without importing/running the real Qt GUI. Real Bazzite verification is complete: disconnected and connected star clicks changed only favorite state; clicking the server row while connected still used the existing server-switch confirmation; the popup opens at the top in favorites → Fastest → normal ping order; search, persistence and the 10-item limit passed during repeated use; the yellow/gold stars and font-independent Fastest vector bolt render correctly; and an isolated catalog-missing-favorite simulation proved that the retained row is disabled/non-connectable, remains removable through its star, disappears immediately after removal, and does not reappear through search. The lack of hover highlighting on the disabled unavailable row is an intentional Qt/safety tradeoff rather than a bug: making it appear selectable would require re-enabling the row and manually blocking every activation path for cosmetic benefit. Treat Stage 2B as verified.


**Stage 2C verified — root-level dynamic tray Favorites submenu (2026-08-12):**

- When one or more favorites are saved, the tray root contains a separate `Favorites` / `Favoriten` submenu immediately after the existing `Connect to…` / `Switch server…` submenu and before the separator that leads to Show/Quit. This is a sibling submenu, not content nested inside the normal server submenu. With zero saved favorites, the Favorites submenu does not exist at all.
- The existing Connect/Switch server submenu remains intentionally unchanged: Fastest, its normal ping-sorted quick-region list and Full server list continue to work exactly as before. Favorite regions may therefore still appear in that ordinary server list; Favorites is an additional personal shortcut, not a replacement/filter for the normal server picker.
- The top-level Favorites submenu intentionally has no star/icon; only the individual favorite actions use the yellow/gold star marker. Available favorites are resolved only from the current PIA catalog and call the existing `connect_region()` path, preserving disconnected connect, connected server-switch confirmation and Kill-Switch-protected switching without parallel VPN logic.
- A catalog-missing favorite remains visible inside Favorites using only its safe stored display snapshot plus `Not available` / `Nicht verfügbar`; that action is disabled and cannot call `connect_region()`. Missing non-favorites are never synthesized.
- The Favorites parent menu obeys the same connection-safety gating as other tray connection actions: unknown network state, a busy connection transition or a blocking/recovery Kill-Switch state disables the submenu rather than bypassing existing safeguards.
- `_toggle_region_favorite()` rebuilds the tray after every successful add/remove. Therefore adding the first favorite creates the submenu, adding/removing further favorites updates its contents, and removing the final favorite removes the submenu on the next tray-menu opening without restarting PIA Bazzite or refreshing the server catalog.
- Focused Stage 2C regression coverage lives in `tests/ui/test_server_favorites_stage2c.py`; `tools/0.7-stage2c-tray-favorites-self-test.sh` runs Stage 2A, Stage 2B and Stage 2C checks plus the existing release self-test without touching the real tray, network, helper, firewall or NetworkManager. Real Bazzite verification is complete: the Favorites submenu appears immediately after adding the first favorite, updates on the fly as favorites are added/removed, and disappears completely after removing the final favorite; selecting a favorite while disconnected uses the normal connect path; selecting another favorite while connected keeps the existing server-switch confirmation and successfully switches through the established connection/Kill-Switch path. Stage 4C later supersedes only the cosmetic icon placement: Favorites gets one top-level menu icon and the redundant per-row gold stars are removed. Treat the functional Stage 2C behavior as verified.

**Stage 2D verified — integrated server-favorites freeze (2026-08-12):**

- The complete favorites stack was rechecked together after the separate 2A/2B/2C commits. All three focused self-test gates passed in sequence with the inherited release self-test still green.
- Real Bazzite integrated verification passed with persisted favorites after restart; main-window ordering `favorites → Fastest → remaining regions by ping`; popup opening at the top; live add/remove synchronization between the main window and tray; search behavior; the 10-favorite cap; direct tray connect while disconnected; confirmed tray server switching while already connected; and the existing Kill-Switch-protected server-switch path.
- Previously completed focused proofs remain authoritative for the catalog-missing edge case: an unavailable favorite stays visible but disabled/non-connectable, its star remains removable, removing it deletes the retained row immediately, and a missing non-favorite is never synthesized.
- Stage 2 introduces no parallel VPN connection path: main-window row selection and tray favorite actions continue to reuse the existing connection/server-switch machinery. The favorite store remains identity/display-only and never supplies stale endpoint data.
- Treat the complete **Server Favorites** feature as integrated and frozen for 0.7 development. Future changes to favorites must preserve the Stage 2A/2B/2C invariants and rerun the corresponding focused gates plus a targeted real UI/tray check.

**Stage 3A verified — Options-window foundation (2026-08-12):**

- The former visible `Options` / `Optionen` menu is renamed to `Tools` in English and `Funktionen` in German so the menu can contain an `Options…` / `Optionen …` dialog entry without the awkward `Options → Options…` duplication. `Funktionen` was chosen after real-UI review because it fits the direct Session Kill Switch/action entries better than the initially tried `Extras`. The internal `options_menu` object name is not a public UX contract.
- The fixed-size Options dialog contains only ordinary persistent preferences: language, appearance/theme, behavior when quitting with an active VPN, and whether the system-tray icon is shown. The dialog is transactional: Cancel changes nothing; Save applies the selected values through the existing main-window preference paths.
- `Re-enter credentials…`, `Show Live Log`, and the Kill Switch toggle deliberately remain direct Tools/Funktionen actions. Credential re-entry is a command rather than a preference; Live Log is a frequent diagnostic/view toggle and keeps `Ctrl+L`; the Kill Switch is an immediate security state change that may require privileged verification and therefore must not be hidden behind a generic modal settings transaction.
- The user-facing toggle is now explicitly named `Use Session Kill Switch` / `Session Kill Switch verwenden`. This reflects the already-documented security boundary: protection is fail-closed while the current system session is running but is not boot-persistent across reboot/kernel crash/power loss. Do not casually shorten this toggle back to a generic `Kill Switch` label. Status summaries may remain concise where context is already clear.
- Stage 3A intentionally adds no public-IP/geolocation provider logic yet. The Options window is the UI foundation for the next provider-selection stages; current candidate design remains Automatic/Recommended as the default with a small number of maintained free alternatives rather than an unbounded provider list.
- Focused static regression coverage lives in `tests/ui/test_options_dialog_stage3a.py`; `tools/0.7-stage3a-options-window-self-test.sh` runs it together with the existing release self-test without importing/running the real Qt GUI. The focused Stage 3A gate and inherited release self-test passed. Real Bazzite verification is complete: the dialog keeps its fixed size; all selector fields use the accepted common alignment/width; Cancel leaves all preferences unchanged; language and System/Light/Dark appearance changes apply correctly; all active-VPN quit-behavior choices retain the established behavior; tray visibility can be disabled/re-enabled; and saved choices persist across reopening/restart. The German `Funktionen` label was accepted for this stage. A possible later cosmetic rename back to `Extras` is explicitly a separate polish decision and must not reopen or destabilize the verified Stage 3A behavior. Treat Stage 3A as verified.

**Stage 3B verified — public-network provider core + real virtual-location comparison (2026-08-12):**

- Stage 3B deliberately changes **no user-facing provider setting and no production default yet**. The normal GUI path still resolves public IP/country through `country.is` only as a temporary compatibility default until the later Automatic/local-database stage replaces it.
- The old public-network lookup implementation was isolated from `pia_api.py` into `pia_bazzite/public_network.py`. `pia_api.fetch_public_network_info` remains available through a compatibility import, so the GUI call path and existing worker/error behavior do not need to change merely to introduce provider architecture.
- Complete validated adapters exist for the legacy `country.is` path, Cloudflare `/cdn-cgi/trace`, `ipwho.is`, FreeIPAPI, and GeoJS. Every adapter validates the returned numeric IP and two-letter country code before exposing a `PublicNetworkInfo`; malformed responses, explicit provider failures, timeouts and transport errors fail cleanly through the existing public-IP error surface. GeoJS is a maintained candidate because its real-host results were strong; the one-off `ipapi.is` experiment is deliberately not part of the product core.
- Amazon `checkip.amazonaws.com` is intentionally modeled as **IP-only**, not as a fake geolocation provider. The planned `Automatic (recommended)` mode is intended to combine Amazon public-IP discovery with a local IPinfo Lite country database and a defined IP-discovery fallback. Do not expose Amazon as a standalone country provider.
- Real Bazzite comparison covered seven PIA locations including difficult virtual locations: Monaco, Liechtenstein, Turkey, Isle of Man, Belgium, Luxembourg, and Georgia. FreeIPAPI, GeoJS, and ipwho.is returned the selected PIA country in all recorded runs. By contrast, `country.is` and Cloudflare both misclassified Monaco as GB, Liechtenstein as NL, and Turkey as DE; therefore neither is planned as a selectable country provider. Isle of Man is an important counterexample showing that a PIA virtual location can still geolocate cleanly across all tested databases.
- Final product direction after the comparison: maintained free online choices are FreeIPAPI, GeoJS, and ipwho.is; **GeoJS is the default** because it produced the strongest observed PIA virtual-location results. Cloudflare may still be considered as an internal **IP-discovery** fallback, but not as a country provider. `ipapi.is` was tested successfully after accounting for its anonymous response shape, but is intentionally omitted from the maintained option set to keep the list small and avoid another key/rate-limit policy surface.
- Later Stage 3C testing added Nigeria virtual as an important extra discriminator: GeoJS returned `NG`, while FreeIPAPI and ipwho.is returned `ES`. A local IPinfo Lite/MMDB design was then evaluated and deliberately rejected before implementation: for a small “detected country” feature, bundling and keeping a roughly tens-of-megabytes geolocation database fresh would add disproportionate packaging, update, token/build-secret, failure-handling, and maintenance complexity. Do **not** revive the local-IPinfo plan unless a future requirement justifies that extra infrastructure.
- `tools/0.7-stage3b-public-network-provider-probe.py` remains as the simple read-only manual comparison tool that proved the real behavior. The accidentally overbuilt CSV benchmark helper was research-only and must not be committed.
- Focused regression coverage is `tests/connection/test_public_network_providers.py`; `tools/0.7-stage3b-public-network-provider-self-test.sh` runs the provider tests plus the verified Stage 3A options-window checks. The focused Stage 3B gate and inherited release gate are green, and the real provider comparison above is complete. Treat Stage 3B as verified.

**Stage 3C verified — selectable online public-IP/location providers (2026-08-12):**

- Stage 3C adds the first genuinely new setting to the Options dialog under a dedicated Network group: `IP-/Standorterkennung` / `IP/location detection`. It uses the same fixed 230 px label column and 250 px selector width established by Stage 3A; the dialog remains fixed-size and grows only enough to fit the new group.
- The user-facing online choices are deliberately limited to **FreeIPAPI**, **GeoJS**, and **ipwho.is**. They were the three strongest maintained candidates from the original Stage 3B comparison. Legacy `country.is` and Cloudflare adapters remain in the core only for regression/research use and must not appear in the selector.
- **Verified 0.7 default: GeoJS.** During real Stage 3C testing, a Nigeria virtual PIA exit was a new discriminator: GeoJS returned `NG`, while both FreeIPAPI and ipwho.is returned `ES` for the same selected virtual location. Combined with the earlier Monaco/Liechtenstein/Turkey/Isle-of-Man/Belgium/Luxembourg/Georgia runs, GeoJS is the strongest observed online provider and is therefore the fallback/default for missing or corrupt provider preferences. The selector labels it `GeoJS (Standard)` / `GeoJS (Default)` so the user can see the recommended baseline without adding another synthetic Automatic mode.
- Provider choice is stored under `network/public_info_provider`. Unknown/corrupt persisted values normalize safely back to GeoJS rather than becoming arbitrary URLs or provider IDs. Saving a changed provider immediately performs a normal read-only public-info refresh through the existing worker path, so the user can visibly compare providers without restarting the app. Cancel still applies nothing.
- The provider selector includes a privacy tooltip explaining that the selected online service sees the public IP during lookup. No API keys, user credentials, VPN configuration, helper state, firewall state or Kill-Switch state are passed to these services.
- Focused coverage is `tests/ui/test_public_network_provider_options_stage3c.py`; `tools/0.7-stage3c-provider-options-self-test.sh` runs the Stage 3B core, inherited Stage 3A UI invariants, and Stage 3C selector/runtime integration tests. The focused Stage 3C gate and authoritative unprivileged release gate are green. Real Bazzite verification is complete: all three providers refreshed the displayed public IP/country immediately without changing VPN or Kill-Switch state; Cancel discarded an unsaved provider change; the saved provider survived reopening and full app restart; and no Polkit/admin prompt was introduced. Treat Stage 3C as verified.
**Stage 3D verified — compact server markers + tray polish (2026-08-13):**

- The main server selector and the tray quick server/favorites menus use the same compact neutral markers: `●` means a PIA virtual location and `▶` means a streaming-optimized location. The final `●` marker was chosen after real Bazzite visual testing because font-based globe-like alternatives were either visually ambiguous or inconsistent under Qt/Linux; do not replace it with an emoji/globe glyph without a deliberate visual regression test.
- Hover QuickInfo explains only the non-obvious marker meanings (`Virtueller Standort` / `Virtual location`, `Streaming-optimierter Standort` / `Streaming-optimized location`). The redundant ordinary favorite add/remove instructions were removed because the separately clickable star is self-explanatory. Catalog-missing favorites retain their existing unavailable/safe-removal explanation.
- Missing favorite snapshots derive the same compact markers only from the already persisted safe `geo` flag and last-known name. No stale endpoint, hostname, IP or ping data is added to favorite persistence, and unavailable favorites remain non-connectable.
- The disabled informational tray status row (`Getrennt` / connected status text) intentionally has **no separate status-dot icon**. The actual tray icon already communicates VPN/Kill-Switch state by color; keeping a static gray dot there would add no useful state information and would visually conflict with `●` as the virtual-location marker.
- Verbose region wording remains available for explanatory/log/confirmation surfaces that are not compact server-picking menus. The Stage 3D change is presentation-only and introduces no new VPN, provider, favorite, or Kill-Switch path.
- Focused coverage is `tests/ui/test_server_markers_stage3d.py`; the final focused gate is 9/9 PASS. The relevant inherited tray/runtime coverage passes, the authoritative unprivileged Stage-8C.2 release gate passes, and real Bazzite verification confirms the final `●`/`▶` appearance, simplified QuickInfo, compact tray labels, and removal of the redundant tray status dot. Treat Stage 3D as verified and frozen.

- **0.6.1:** only if real bugs/hardening/maintenance items accumulate; do not release solely for the reboot-scope README clarification.
**Stage 4A verified — Auto-Connect Options foundation (2026-08-13):**

- Auto-Connect begins as an ordinary, non-privileged persistent preference only. Stage 4A **does not** start a VPN automatically, request Polkit, alter NetworkManager, touch the Session Kill Switch, or change A13 clean-start behavior. Real startup execution belongs to Stage 4B.
- UX is intentionally one selector rather than a checkbox plus second selector: `Off`, `Last selected location`, then current Favorites, `Fastest location`, then the remaining current catalog sorted by ping. Favorite/current-server labels reuse the compact Stage 3D `●`/`▶` marker wording.
- Favorite choices use the same yellow/gold star icon as the main server selector, and `Fastest location` uses the same yellow/gold vector lightning icon. The popup is capped at roughly 20 visible rows and then scrolls, matching the compact behavior of the main server chooser.
- The Auto-Connect QuickInfo is deliberately two paragraphs: the first explains what the preference selects; the second makes clear that Stage 4A only stores the preference and that actual startup connection comes in a later 0.7 stage.
- A fixed-location Auto-Connect choice stores only the PIA `region_id` (`region:<id>`), never endpoint IP/hostname/ping data. If that exact region disappears from the current PIA catalog, keep the saved choice visible but disabled and **do not silently fall back to another country/location**. `Fastest` is the only mode that intentionally chooses a different region dynamically.
- Real Bazzite verification passed for the fixed-size Options layout, selector ordering, favorite grouping, yellow favorite/fastest icons, approximately 20-row scroll cap, marker rendering, QuickInfo paragraph break, Save/Cancel behavior, and persisted selection. The selector remains preference-only and caused no startup connection or authorization prompt during Stage 4A testing.
- Focused coverage is `tests/ui/test_auto_connect_options_stage4a_07.py`; `tools/0.7-stage4a-auto-connect-options-self-test.sh` reruns the verified Stage 3A/3C/3D UI invariants. Final focused gate: **35/35 PASS**. The authoritative unprivileged Stage-8C.2 release gate also passes. Treat Stage 4A as verified and frozen.


**Stage 4B verified — Auto-Connect startup execution (2026-08-13):**

- Stage 4B activates the Stage 4A preference but deliberately adds no second VPN implementation. Once the startup gates are satisfied, Auto-Connect resolves one target and calls the already audited `connect_region()` path; helper authorization, credential use, normal IPv6 guard setup, Session Kill Switch ordering, logging, success/failure handling and post-connect verification therefore remain shared with manual connections.
- Startup execution is one-shot per app process. `Off` completes without helper/Polkit access. If Auto-Connect was off when startup evaluation already completed and the user enables it later, it applies on the next app start instead of becoming a delayed surprise connection.
- Auto-Connect waits until the first-run credentials flow has completely finished, the initial live PIA catalog + ping refresh has completed successfully, clean/required Session Kill Switch startup reconciliation has reached a safe decision, and normal IPv6-guard startup reconciliation has also safely settled. Qt timers may run inside the first-run credentials dialog, so the explicit `startup_first_run_flow_complete` gate is required to prevent a false `credentials missing` decision while that modal dialog is still open.
- Existing VPN/recovery state has priority. If a VPN is already connected, Auto-Connect skips. A fail-closed disconnected Kill Switch recovery state is never bypassed through normal `connect_region()`; recovery/protected reconnect remains authoritative. Startup reconciliation failure/refusal does not mark the relevant safety gate complete, so Auto-Connect cannot race past it.
- Target resolution preserves Stage 4A semantics: fixed `region:<id>` and `Last selected location` resolve only to that exact current region ID; a missing fixed/last region produces no fallback. `Fastest location`, and a last selection that was explicitly the Fastest pseudo-entry, dynamically resolve to the fastest **reachable** freshly pinged region.
- The initial region refresh is part of the startup gate. If that live refresh fails, Auto-Connect is skipped for the process rather than connecting later after a manual refresh or using a potentially stale location as an implicit fallback. This avoids delayed surprise connections and stale-target ambiguity; manual connection remains available.
- First-run credential cancellation suppresses Auto-Connect for that process so PIA Bazzite does not immediately reopen the credential dialog the user just cancelled. NetworkManager status uncertainty likewise skips Auto-Connect instead of assuming disconnected.
- The Options QuickInfo now describes active startup behavior and states that existing VPN/protection/recovery states take priority. New DE/EN Live-Log messages explain start, already-connected skip, recovery priority, unavailable target/server list, missing credentials, busy startup, and unknown VPN state.
- Focused coverage is `tests/ui/test_auto_connect_startup_stage4b_07.py`; `tools/0.7-stage4b-auto-connect-startup-self-test.sh` runs Stage 4A plus startup, idle-quit, Kill-Switch recovery, and IPv6-guard regression coverage. Final focused gate: **38/38 PASS**. The authoritative unprivileged Stage-8C.2 release gate also passes.
- The complete real-Bazzite Stage 4B matrix passed on 2026-08-13: `Off` + Session Kill Switch armed produced no Auto-Connect and no startup authorization; `Last selected location` reconnected exactly to Isle of Man; `Fastest location` freshly selected Deutschland – Frankfurt at 14 ms even though it was not the prior server; a fixed ordinary region reconnected exactly to Croatia; an already-active ordinary VPN + IPv6-only guard was adopted after app restart and Auto-Connect explicitly skipped; and a fixed Auto-Connect target with Session Kill Switch disabled connected successfully to Croatia in normal VPN mode and ended Blue.
- Important authorization clarification from the final host matrix: **Session Kill Switch disabled does not imply a password-free Auto-Connect.** Ordinary connected mode still installs/verifies the privileged IPv6-only firewall guard that prevents native IPv6 from bypassing PIA's IPv4-only WireGuard tunnel, so a fresh app session may legitimately request administrator authorization for that guard. This is separate from Session Kill Switch authorization and is part of the current leak-prevention design; do not remove it merely to suppress the login prompt.
- A fixed favorite (`Isle of Man`) with Session Kill Switch enabled also completed the intended firewall-first startup order — fresh server/ping refresh, Auto-Connect target resolution, authorization/protection, NetworkManager WireGuard start, final VPN + Kill Switch verification, crash-recovery record persistence, and correct public-network refresh. Treat Stage 4B as **verified and frozen**.

**Stage 4C verified — login autostart + top-level tray icon polish (2026-08-13):**

- Options adds `PIA Bazzite at login` / `PIA Bazzite bei der Anmeldung starten` as an ordinary user preference backed by PIA Bazzite's own XDG autostart desktop entry under `$XDG_CONFIG_HOME/autostart` (normally `~/.config/autostart`). No root/Polkit operation is involved in toggling it. Disabling removes only PIA Bazzite's own desktop-entry filename.
- The autostart Exec command deliberately does not point into an AppImage mount. When `APPIMAGE` is present, persist the original AppImage path plus the internal `--autostart` argument; source/development runs persist the active Python executable plus the absolute `main.py` path. Exec arguments are Desktop-Entry quoted and literal `%` characters are escaped as field-code literals; no shell command is generated.
- `--autostart` is removed before Qt argument processing. A login-autostart launch suppresses `window.show()` only when the tray is actually enabled after MainWindow initialization; if the tray setting is disabled or the desktop provides no usable system tray, the main window is shown so the app can never become unreachable. Manual launches keep the normal visible-window behavior.
- A duplicate login-autostart invocation must not raise an already-running PIA Bazzite window. `SingleInstance.claim()` therefore keeps its existing activation behavior by default but can probe/exit silently for the `--autostart` path.
- Tray polish is top-level only: connect/disconnect, Connect/Switch server, Favorites, Show, and Quit receive desktop-theme icons with small neutral vector fallbacks. The disabled status row remains icon-free because the real tray shield already conveys state. Favorite child rows keep their compact server markers but no longer repeat a gold star; the Favorites parent owns the visual favorite icon. Nested server actions otherwise retain their established behavior, including the Fastest marker.
- Stage 4C must not alter Stage 4B target resolution, startup safety gates, Session Kill Switch ordering, Auto-Connect one-shot semantics, or the existing tray connection/favorite action paths.
- Focused coverage is `tests/ui/test_autostart_tray_stage4c_07.py`; `tools/0.7-stage4c-autostart-tray-polish-self-test.sh` also reruns Stage 4B, Stage 4A, Stage 2C, Stage 3A, and single-instance/static regression coverage. Real Bazzite verification confirms the Plasma top-level tray icon rendering, a dry `--autostart` launch, a full reboot/login XDG-autostart path with Auto-Connect, hidden-in-tray startup when the tray is enabled, and visible-main-window fallback when the tray is disabled. The Auto-Connect Options popup deliberately opens at row zero every time, matching the main server selector and ensuring `Off` is immediately visible even when another target is selected. Final selector polish groups the special modes first (`Off`, `Last selected location`, then gold Fastest), gives Off/Last neutral desktop-theme icons with neutral vector fallbacks, keeps gold stars on favorite rows, removes only the redundant disabled `Favorites` heading, and then shows the ordinary ping-sorted region list. The final selector presentation was visually confirmed on real Bazzite after the popup-top fix: `Off` is always immediately visible, Off/Last/Fastest are clearly distinguished from ordinary regions, favorites retain their gold stars without a redundant `Favorites` heading, and the normal region list follows cleanly below. Treat Stage 4C as verified and frozen; no further functional autostart/tray behavior changes are planned.

- **0.7.x current sequence:** Stage 3A Options-window foundation, Stage 3B provider-core/real-location comparison, Stage 3C selectable online providers, Stage 3D compact server-marker/tray polish, and Stage 4A Auto-Connect preference foundation are complete and verified. GeoJS is the verified 0.7 default after the Nigeria virtual-location discriminator, with FreeIPAPI and ipwho.is available as maintained user-selectable alternatives. The local IPinfo Lite/Automatic design was consciously rejected as disproportionate complexity for this feature. **Stage 4B Auto-Connect startup execution and Stage 4C login-autostart/tray behavior (including the final Auto-Connect selector presentation) are both verified and frozen.** Improved network-change handling remains a later 0.7 candidate. Server Favorites are complete and verified.
- **0.8.x candidates:** trusted networks and an optional, carefully tested local-LAN access exception for the Kill Switch.
- **0.9.x candidate:** PIA port forwarding on supported regions.
- **Later / high risk:** per-app split tunneling. Treat it as a routing/security project comparable in complexity to the Kill Switch, not a small checkbox.
- **Potential architectural maintenance:** gradually split the large GUI/controller and introduce/style-gate tools such as Ruff/optional type checking, but never mix a broad refactor into an urgent security patch.
- **Possible larger security feature:** boot-persistent/early-boot protection would be a separate major design effort involving systemd, lockout recovery, update/uninstall safety and boot networking. It is not a 0.6.1 patch.
- **1.0.0:** reserve for a mature overall product rather than using the number as a deadline.

---

## 17. Starting a new development chat

Best workflow:

### Step 1 - archive the actual current checkout

From the parent directory:

```bash
cd "$HOME"

tar \
  --exclude='PIA-Bazzite/.git' \
  --exclude='PIA-Bazzite/.venv' \
  --exclude='PIA-Bazzite/build' \
  --exclude='PIA-Bazzite/dist' \
  --exclude='PIA-Bazzite/__pycache__' \
  --exclude='PIA-Bazzite/**/__pycache__' \
  -czf "$HOME/PIA-Bazzite-current.tar.gz" \
  PIA-Bazzite
```

If the checkout contains additional generated packaging/staging directories in a future version, exclude those too. Do **not** exclude maintained source tests/docs merely to make the archive smaller.

### Step 2 - upload two files

Upload:

1. `PIA-Bazzite-current.tar.gz`
2. this `docs/HANDOFF.md`

### Step 3 - tell the new ChatGPT instance

For example:

```text
We are continuing development of PIA Bazzite.
Please read docs/HANDOFF.md first, then inspect the complete current source archive before proposing code changes.
The source tree is authoritative for exact code; the HANDOFF explains architecture, verified behavior and historical traps.
```

### Step 4 - do not patch immediately

The new assistant should reconcile the current tree with this HANDOFF first. If the HANDOFF claims something that the source no longer implements, inspect Git/history/current tests before assuming either side is correct.

---

## 18. Quick “do not regress” checklist

Before declaring a future change finished, ask:

- Did I inspect the current complete source before changing it?
- Does normal disconnected startup with Kill Switch remembered ON remain Polkit-free?
- Does quitting immediately from that clean armed-only state remain Polkit-free while real/ambiguous recovery state still forces the privileged recheck?
- With Kill Switch OFF, is the exact IPv6-only guard active before/while the VPN is connected and removed only after verified intentional disconnect?
- Can native IPv6 bypass the normal VPN? It must not.
- With Kill Switch ON, is the full firewall active and verified **before** NetworkManager starts the VPN?
- Are `pia_bazzite_ipv6_guard` and `pia_bazzite_killswitch` still separate, correctly owned states?
- Is `unknown` still distinct from `disconnected`?
- Does intentional protected disconnect verify VPN-down before releasing the firewall?
- Does forced tunnel loss remain fail-closed and recover under the existing lock?
- Does protected server switching retarget endpoint exceptions while the lock remains active?
- Does GUI SIGKILL leave kernel protection intact and allow exact restart adoption?
- Can a blocked crash state restart directly into Orange without an unrelated server-list modal racing Polkit?
- Are crash-recovery records still treated only as hints and verified against live state?
- Does Reset Kill Switch Protection remain VPN-first, fixed-table-only, verified, explicit and never automatic?
- Does reset copy still warn that normal networking afterward is outside VPN protection and the real public IP may be visible?
- Does the installed root helper bootstrap still verify ownership/modes/manifest/checksums before importing installed helper package code?
- Can a user-controlled path, table name or arbitrary command cross the privileged helper boundary? It should not.
- Does Polkit cancellation before mutation leave VPN/firewall unchanged and present a neutral cancellation result?
- Does single-instance protection prevent two competing GUI/controllers?
- Do server favorites remain capped at 10, user-owned, and persistent without silently deleting catalog-missing favorites?
- Is a catalog-missing favorite non-connectable without using stale endpoint data, while a catalog-missing non-favorite disappears normally?
- Does `ping_ms is None` remain distinct from a region being absent from the PIA catalog?
- Do Live Log/public diagnostics remain free of credentials, PIA tokens and WireGuard private keys?
- Is disconnected public-IP lookup still manual-only?
- Are public docs still honest about reboot scope, Limited connectivity and IPv6 behavior?
- Are public GitHub docs still English while runtime localization remains DE/EN?
- If packaging/release changed, are helper payload provenance, licenses/notices, Action pins, exact commit/tag identity and AppImage checksum still verified?
- Did I run the changed-area regression plus the critical safety subset appropriate to the change?

If these answers are yes, the change is much less likely to undo one of the hard-won 0.6.0 safety properties.

---

## 19. Historical 0.6.0 development record

The sections below preserve detailed Stage-8 decisions and real-host findings. They are **historical evidence**. Any old sentence saying “next step”, “awaits”, “current candidate” or similar describes that moment in development and must not override the current release state at the top of this HANDOFF.

### Earlier Stage-8 summary

- **8C.1 full code audit:** found and fixed release-sensitive issues including packaged-helper privilege-handoff TOCTOU/downgrade risk, NetworkManager query failures being collapsed to disconnected, stale security documentation, WireGuard-config safety, PIA response validation, single-instance serialization, public-IP privacy, CI/release coverage and packaging hygiene.
- **8C.2 hardening:** fixed helper payload anchoring/staging, unknown NetworkManager state, private WireGuard config creation, validated PIA network values, single-instance stale-socket serialization, disconnected public-IP behavior, source privacy and deterministic packaging/provenance/license handling.
- **8C.3 real RC:** exercised normal VPN, IPv6 containment, full Session Kill Switch, protected recovery/switching, crash adoption, integrated reset, tray/exit/settings/suspend/offline and UI behavior on real Bazzite.
- **8D freeze:** finalized release date/metadata, pinned external GitHub Actions, committed exact release tree, required clean CI, and tagged the exact release commit as `v0.6.0`.

### Stage 8C.2 packaging license-material correction

The real packaging host gate exposed that PySide6-Essentials 6.11.1 cannot be
assumed to expose its open-source license texts through wheel metadata. The
release build therefore bundles hash-pinned canonical LGPLv3, GPLv3 and GPLv2
texts under `usr/share/doc/pia-bazzite/third-party-python/PySide6-Qt/` and the
host gate verifies their exact hashes. Do not weaken this back to a
wheel-layout-dependent check.

## Stage 8C.3A first-run UI/runtime regression (2026-08-07)

A clean first-run test caught a release-blocking server-list regression that automated packaging tests did not catch. PIA's public `vpninfo/servers/v6` feed currently exposes 189 regions and WireGuard `cn` values may be single-label certificate names (for example `helsinki403`), not only dotted DNS names. The 8C.2 input hardening must therefore accept safe single-label certificate names while continuing to reject control characters and malformed labels.

First-run UX rules now also include: do not start the initial server-list refresh while the credentials dialog is still modal; a stored password is not claimed to be validated until a VPN connection actually authenticates; disconnected public IP/country show an explicit "Not checked" state until the user requests the lookup; and Live Log expanded height is derived from the actual panel minimum so the buttons do not overlap after the taller Kill-Switch status card.

### Stage 8C.3A dynamic Live Log regression-test correction

After the dynamic Live Log height fix, the old Stage-4B/4C preview smoke tests
still required the historical exact `760x780` window size. That assertion is
stale: 780px is now only the legacy minimum, while the real expanded height is
derived from the current log-panel minimum. Preview gates must validate the
computed expanded size and explicitly prove that the Copy/Save/Clear buttons do
not overlap the log text view; do not reintroduce an exact 780px height check.


### Stage 8C.3A final UI polish decisions (2026-08-07)

The clean first-run/manual UI pass found no further release-blocking VPN/Kill-Switch behavior after the server-list correction. A practical Wi-Fi disconnect/reconnect and suspend/resume smoke check also behaved as expected; the formal final regression still remains required.

Final 0.6.0 polish requirements:

- load and package Qt's German `qtbase_de.qm` translation so standard Qt buttons and file-dialog labels follow the app language;
- keep the two separate administrator authorizations for first-time Kill Switch helper installation/session startup, but explain in the confirmation dialog that two prompts may appear; do not merge the audited privilege boundaries before 0.6.0;
- Live Log follows new entries only while already at the tail, jumps to the newest entry when newly shown, and also catches up when the user returns from tray-driven actions; intentional manual scrolling upward must not be constantly overridden while the window remains visible;
- main server combo shows at most 20 visible rows before scrolling; the tray quick list uses the first 20 reachable regions and retains the full-list action;
- public-IP reload control is slightly smaller (`24x22`);
- replace the generic About message box with a TrainerBridge-like application dialog: centered app icon/name/version/description/license/developer/disclaimer and buttons for Project Page, Third-Party Notices, and Close;
- keep current wrong-password behavior: credentials are saved without claiming validation, and PIA rejects invalid credentials on actual connect.

Post-0.6.0 UX roadmap note — superseded in 0.7 development: Stage 3A now introduces the real Options dialog using existing persistent UI preferences first; later 0.7 stages will add public-IP/geolocation provider choice, while Auto-Connect, trusted networks and LAN access remain future candidates.

### Stage 8C.3A Qt-translation import-boundary correction (2026-08-07)

The first final-polish self-test exposed a non-GUI import regression: adding Qt standard-dialog translation support made `pia_bazzite.i18n` import `PySide6.QtCore` at module import time. Core modules such as `pia_api`, `app_errors`, and `network_manager` import `tr()` and must remain importable in the unprivileged/system-Python security tests where PySide6 may be intentionally absent. Qt classes are therefore imported lazily only when Qt translation support is actually applied. Do not restore a top-level PySide6 import in `i18n.py`; a regression test now enforces this boundary. The AppImage still bundles and uses `qtbase_de.qm` during real GUI execution.

### Stage 8C.3A first normal-VPN IPv6 route-fix attempt — superseded (2026-08-07)

**Historical note: this subsection records the first attempted route-only fix.
It is superseded by the later real-host correction and A7 firewall-guard
architecture below; do not implement its blackhole-route prescription.**

Manual dual-stack testing found a release blocker in **normal VPN mode with the
Kill Switch disabled**. IPv4 correctly used `piabazzite`, but IPv6 could still
use the physical interface. The profile already contained a blackhole IPv6
default route, so the GUI reported "IPv6 protection: Blocked" merely because
that route existed. On the real host the physical Router-Advertisement default
route had metric 600 while the unpinned blackhole used the IPv6/default metric
(typically 1024), so the physical route could win.

0.6.0 must therefore keep these invariants separate:

- normal VPN mode is **not** a Kill Switch; when the VPN is intentionally
  disconnected or later disappears, normal connectivity may return;
- while PIA Bazzite reports the normal VPN as connected, IPv4 must use the
  WireGuard path and native IPv6 must not run in parallel outside the tunnel;
- the PIA WireGuard NetworkManager profile pins its IPv6 blackhole default route
  to the main table with metric 1 and post-verifies the effective IPv6 routing
  decision; if verification fails, the just-started VPN is disconnected again
  instead of presenting a connected-but-leaking state;
- `ipv6_blackhole_active()` must verify the **effective route decision**, not
  merely the existence of any blackhole route;
- the optional Session Kill Switch remains the separate stronger fail-closed
  firewall feature and continues to block IPv4/IPv6 during tunnel loss.

Why earlier testing missed this: the authoritative Kill-Switch host/namespace
suites deliberately verified IPv6 fallback **while the firewall lock was
active**, and those tests passed. They did not independently force dual-stack
egress in the ordinary non-Kill-Switch connection path. The GUI check also only
looked for blackhole-route existence, and public-IP lookups often succeeded over
IPv4, masking the competing IPv6 route. Keep an explicit real-host normal-mode
IPv4/IPv6 route check in the final release regression.

A read-only `tools/pia-bazzite-network-debug.sh` diagnostic is now part of the
project. It reports NetworkManager profile/routing decisions, WireGuard endpoint
and AllowedIPs (never private keys), IPv4/IPv6 policy routing, DNS and country-only
family egress checks; it redacts source addresses and performs no network
mutation.

### Stage 8C.3A real-host correction: NetworkManager route-only IPv6 containment failed (2026-08-07)

The first attempted normal-mode IPv6 fix is **not valid on the real Bazzite host** and must not be treated as a completed fix. Real-host evidence supersedes the earlier route-only assumption:

- ordinary VPN with Kill Switch OFF routes IPv4 through `piabazzite` but public IPv6 through the physical interface (`wlo1`); a Netherlands test proved IPv4 country `NL` while IPv6 country remained `DE`;
- NetworkManager 1.56.1 stores `ipv6.method=manual`, main-table route 254, route metric 1 and `::/0 type=blackhole` in the PIA profile, but the effective kernel main table still exposes the physical IPv6 default route and a live route monitor observed no blackhole route installation;
- a second isolated NetworkManager sink-route experiment was accepted by the profile but still selected `wlo1` for public IPv6 while IPv4 selected `piabazzite`; therefore do **not** try a third route-only variant for 0.6.0;
- the current test build's conservative IPv6 post-check correctly refuses a connected-but-leaking normal VPN, but it is currently coupled too broadly and also prevents the Session Kill Switch connection path from completing. This is a temporary broken development state, **not an RC**.

The Session Kill Switch itself remains the separately proven nftables fail-closed foundation. Stage-5/6/7 host/namespace tests exercised IPv4/IPv6 blocking while that production firewall was active. Do not replace or weaken that architecture because the NetworkManager-only normal-mode guard failed.

**Strategy pivot:** before touching production code again, prove a minimal isolated **IPv6-only nftables guard** on the real host. The probe must show (1) normal IPv4 + IPv6 work before the guard, (2) with only the temporary guard active IPv4 still works while public IPv6 is blocked and the nft rule counter proves enforcement, and (3) after guard removal IPv6 immediately works again. The probe uses its own temporary table and independent systemd cleanup timer and must not touch the PIA profile, production Kill Switch table, helper installation, or project files. Only after this host probe passes should the IPv6-only guard be designed into the verified helper/orchestration path.

Target architecture if the probe passes:

- **Kill Switch OFF + VPN connected:** a narrowly scoped IPv6-only firewall guard prevents native IPv6 bypass; IPv4 uses PIA. This is not a full Kill Switch because IPv4 may return normally if the VPN is not protected.
- **Kill Switch ON:** the existing full Session Kill Switch remains authoritative for both IPv4 and IPv6; do not require the failed NetworkManager blackhole mechanism in addition.
- Keep independent verification and explicit ownership/state separation so the small IPv6 guard can never be mistaken for or silently disable the full Kill Switch.

New isolated proof tool: `tools/pia-bazzite-ipv6-guard-host-probe.sh`. Its result is a release decision input and must be recorded here immediately after the real-host run.

### Stage 8C.3A final polish follow-up

- Main-window server popup must enforce the 20-row cap on the actual popup/view;
  KDE can ignore `QComboBox.setMaxVisibleItems()` for non-editable combo boxes.
- Historical 0.6.0 menu-order note: `Kill Switch verwenden` followed the `Beim Beenden mit aktivem VPN` submenu. In 0.7 Stage 3A those ordinary preference submenus move into the Options dialog, while the direct toggle remains in Tools/Funktionen and is renamed `Session Kill Switch verwenden`.
- About dialog keeps Project Page (`https://github.com/adventureFAN/PIA-Bazzite`),
  Third-Party Notices and Close; remove the Log Folder button for 0.6.0.
- Tray status row shows the connected region/country (or disconnected state);
  the colored tray icon and full tooltip retain protection-state detail.
- Host desktop openers must not inherit PyInstaller's bundled library search
  path. Restore `LD_LIBRARY_PATH_ORIG` (or unset `LD_LIBRARY_PATH`) and clear
  bundled Qt/Python path overrides before launching `/usr/bin/xdg-open`.

### Stage 8C.3A IPv6-only firewall guard host proof + helper foundation (2026-08-07)

The isolated real-host nftables decision gate **PASSED completely** on Bazzite:
25 PASS, 0 WARN, 0 FAIL. Before the guard, numeric public IPv4 and IPv6 both
worked and IPv6 selected `wlo1`. With the temporary guard active, IPv4 continued
to work, public IPv6 was blocked, the exact nftables block-rule packet counter
increased, and the kernel route still selected `wlo1`; this proves enforcement
came from nftables rather than another routing side effect. After guard removal,
both IPv4 and IPv6 worked again and the independent cleanup timer was cancelled.

This result is authoritative for the 0.6.0 strategy pivot: **do not attempt any
more NetworkManager route-only IPv6 containment variants**. The proven normal-
mode containment primitive is an IPv6-only nftables guard.

The next production slice adds a strictly separate helper-owned table
`pia_bazzite_ipv6_guard` with fieldless protocol/session actions
`ipv6-guard-status`, `ipv6-guard-enable`, and `ipv6-guard-disable`. The helper
renders only the already-proven two-rule shape (loopback accept + outbound IPv6
reject at output priority -110), verifies fixed ownership markers/priority/rule
count, and keeps the full Session Kill Switch table `pia_bazzite_killswitch`
completely separate. The unprivileged client/session contract parses a distinct
`IPv6GuardStatus`, so the small guard cannot be confused with the full Kill
Switch status or its endpoint/interface allowlists.

**Important current boundary:** this helper/client foundation is intentionally
not yet wired into `gui.py` or the normal connect/disconnect lifecycle. The
current development GUI still contains the failed NetworkManager blackhole
post-check and therefore is not an RC. Do not remove that temporary fail-safe
until the IPv6 guard lifecycle is integrated and covered by regression tests.
The next substage must design/test: guard-before-normal-VPN-connect ordering,
verified guard status, VPN-down-before-guard-release on intentional disconnect,
failure cleanup, crash/stale-guard behavior, quit-with-connected-VPN behavior,
and explicit non-interference with the existing full Kill Switch path. With Kill
Switch ON, the existing full nftables Session Kill Switch remains authoritative
and must not depend on the failed NetworkManager IPv6 post-check.

A separate `tools/pia-bazzite-ipv6-guard-helper-namespace-test.sh` exercises the
new production helper actions with real nftables inside a root-created isolated
network namespace. It must never be treated as the real-host egress proof (that
proof already passed separately); its purpose is to verify that the restricted
helper creates/removes only the fixed guard table and does not touch the full
Kill Switch table before GUI integration begins.

### Stage 8C.3A.7 normal-VPN IPv6 guard lifecycle integration candidate (2026-08-07)

The production helper foundation has now passed its separate real-nftables
namespace proof on Bazzite: the helper started from a verified disabled guard,
created and independently re-read the exact `pia_bazzite_ipv6_guard` table,
left the full `pia_bazzite_killswitch` table absent throughout, removed only the
small guard again, and finished with **ALL STAGE-8C.3 IPV6 GUARD HELPER NAMESPACE
TESTS PASSED**. Together with the earlier real-host egress probe (**25 PASS, 0
WARN, 0 FAIL**), the firewall primitive and restricted helper boundary are both
proven independently. These results supersede every earlier NetworkManager-only
IPv6 containment attempt.

The current A7 development candidate wires that proven primitive into the normal
VPN lifecycle. The intended and now regression-tested ordering is:

- **Kill Switch OFF / normal connect:** persist an `ipv6_guard_expected` recovery
  marker, verify the exact packaged helper, open one authenticated restricted
  helper session, prove the full Session Kill Switch table is absent, enable and
  independently re-read the small IPv6-only guard, then allow NetworkManager to
  start PIA. NetworkManager must report the fixed PIA profile active and the
  effective public IPv4 route must select `piabazzite`; the small guard is then
  re-read once more before the GUI reports the connection as protected against
  native IPv6 bypass.
- The PIA WireGuard NetworkManager profile no longer pretends to provide IPv6
  containment itself. Its tunnel IPv6 method is disabled and it is marked
  `ipv6.never-default=yes`; native IPv6 containment belongs to nftables. The
  historical blackhole/sink-route logic and `ipv6_blackhole_active()` are removed.
- **Normal intentional disconnect:** NetworkManager is stopped first and
  independently verified down. Only then may `ipv6-guard-disable` run. If VPN
  state becomes unknown or the guard cannot be verified as released, the guard
  is retained instead of being opened blindly.
- **Normal server switch:** the already verified small guard stays active while
  NetworkManager tears down the old profile and creates/activates the new one.
  If the new connection fails and NetworkManager is verified down, the guard is
  released; if VPN state is connected/unknown or guard status becomes unknown,
  the guard is retained fail-safe.
- **Unexpected normal VPN loss while the GUI is alive:** ordinary IPv4 is not
  blocked by this feature and may return immediately, because this is deliberately
  not a Kill Switch. The IPv6 guard stays active until the app independently
  verifies the PIA VPN is down, then it is released. A release failure leaves
  IPv6 blocked and surfaces an explicit error.
- **GUI crash / leave-connected quit:** the small nftables table is kernel state
  and intentionally survives the helper broker/GUI process. The marker remains.
  On restart, a verified guard + active PIA VPN is adopted; a verified guard +
  VPN down is removed; an active PIA VPN without the verified guard is stopped;
  ambiguous state is never treated as safe. If the VPN is disconnected externally
  while the GUI is closed, native IPv6 may remain blocked until the next startup
  reconciliation. This is a deliberate fail-safe tradeoff.
- **Switching the preference to Session Kill Switch:** only while the VPN is
  verified down, a stale verified normal-mode guard is removed first. The helper
  itself additionally refuses to enable the small guard while the full Kill
  Switch table exists and refuses to enable the full Kill Switch while the small
  guard table exists, closing a concurrent-session ambiguity at the privileged
  boundary.
- **Kill Switch ON:** the existing full `pia_bazzite_killswitch` Session Kill
  Switch is authoritative for IPv4/IPv6 fail-closed protection. It no longer
  depends on the failed NetworkManager IPv6 blackhole post-check. Do not add that
  dependency back.

Privilege/UX consequence: because nftables is the chosen reliable containment
mechanism, an ordinary normal-VPN connection now needs an authenticated helper
session to arm the IPv6-only guard. The exact root-owned helper is shared with
but logically separate from the optional Session Kill Switch. The GUI copy must
therefore call it a generic **VPN protection system component**, not imply that
it is needed only when the Kill Switch preference is enabled. The broker is
retained only while the normal VPN/guard is active and closed after a verified
intentional release; a later connection may require a new administrator
authorization depending on the desktop Polkit cache.

Diagnostics are updated for the new architecture. `tools/pia-bazzite-network-debug.sh`
is still read-only/unprivileged and now explicitly expects that the kernel may
continue to choose the physical device for an IPv6 route lookup while actual
IPv6 egress is blocked by nftables. New
`tools/pia-bazzite-ipv6-guard-runtime-check.sh` is a read-only real-host gate that
uses `sudo` only to inspect nftables. In `connected` mode it must prove: PIA active,
IPv4 route via `piabazzite`, full Kill Switch table absent, exact small guard
shape present, public IPv4 TCP usable, numeric public IPv6 TCP blocked, and the
exact guard rule counter incremented. In `disconnected` mode it must prove: PIA
inactive, both production firewall tables absent, and normal IPv4 + IPv6 restored.

### Stage 8C.3A.7 real-host normal-VPN proof (2026-08-08)

The integrated A7 AppImage normal-VPN lifecycle has now passed the real Bazzite
dual-stack host gate with Kill Switch OFF. The authoritative connected runtime
report finished **13 PASS / 0 FAIL**: the PIA WireGuard profile was active, the
public IPv4 route selected `piabazzite`, the full Session Kill Switch table was
absent, the exact `pia_bazzite_ipv6_guard` production shape was present, numeric
public IPv4 TCP worked, numeric public IPv6 TCP was blocked, and the exact guard
block-rule counter increased from **60 to 69** during the blocked IPv6 probe. The
country-only IPv4 egress check reported **NL**, matching the selected Netherlands
server.

The subsequent intentional-disconnect runtime report finished **11 PASS / 0
FAIL**: the PIA WireGuard profile was inactive, both the small IPv6 guard and full
Session Kill Switch tables were absent, and normal public IPv4 plus public IPv6
connectivity were restored. This proves on the real host that the normal-mode
IPv6 guard is active only for the VPN lifetime and does not leave IPv6 disabled
after a verified deliberate disconnect.

This closes the original **normal VPN IPv6 leak release blocker** at the real-host
mechanism/lifecycle level. Keep the two A7 reports as release evidence. The
NetworkManager blackhole and sink-route attempts remain permanently superseded;
do not reintroduce them.

**Current release boundary:** A7 remains a development candidate, **not yet an
RC**, only because the focused **Kill Switch ON** connect/disconnect regression
must now be repeated against this same integrated AppImage. That regression must
prove the full `pia_bazzite_killswitch` table remains authoritative, the small
`pia_bazzite_ipv6_guard` table is absent, IPv4 uses `piabazzite`, public IPv6 is
blocked while protected, intentional disconnect restores normal IPv4/IPv6, and
the A7 normal-mode guard integration has not regressed the already-proven
Session Kill Switch path. Once that passes, Stage 8C.3A can be closed and the
project can move to the final 8C.3 release-candidate functional/UI regression.

### Stage 8C.3A.8 real-host closeout, release copy, and disconnect-state polish (2026-08-08)

The focused A7 Session Kill Switch regression has now passed on the same real
Bazzite dual-stack host used for the normal-VPN guard proof. The connected
report finished **14 PASS / 0 FAIL**: PIA was active, public IPv4 selected
`piabazzite`, the small `pia_bazzite_ipv6_guard` table was absent, the full
`pia_bazzite_killswitch` table had the exact verified production shape, public
IPv4 worked, numeric public IPv6 was blocked, and the full Kill Switch block
counter increased from **101 to 107**. The country-only IPv4 egress check
reported **NL**. The intentional-disconnect report finished **12 PASS / 0
FAIL**: PIA was inactive, both production firewall tables were absent, and
normal public IPv4 plus IPv6 connectivity were restored. Together with the
normal-mode **13 PASS / 0 FAIL** connected and **11 PASS / 0 FAIL** disconnected
proofs, both production protection modes are now independently real-host
verified after the IPv6 architecture pivot.

The original normal-VPN IPv6 leak blocker is therefore closed. The release copy
now explains the user-visible limitation precisely: the WireGuard parameters
currently provisioned to PIA Bazzite by PIA provide an IPv4 tunnel/default route
and no IPv6 `AllowedIPs` route for tunneled IPv6. PIA Bazzite must not invent a
tunnel route that PIA has not provisioned. Native IPv6 is instead blocked only
while the VPN is active and restored after a verified intentional disconnect.
Do not simplify this into a broad claim that PIA as a service never supports
IPv6; the documented claim is deliberately limited to the WireGuard parameters
used by this client.

Project/release credit wording is now a maintained release requirement. Public
release documentation must preserve these two English lines (wording may be
localized inside the GUI About dialog):

`Project direction, feature design, testing, and release decisions: **adventureFAN**`

`Most implementation, debugging, and technical documentation: developed collaboratively with **ChatGPT**`

The About dialog retains the same attribution split instead of the older generic
"Developed by adventureFAN & ChatGPT" line. AppStream's formal developer field
remains `adventureFAN`; the collaboration credit belongs in human-readable
project/release information.

One cosmetic issue was observed during the successful protected disconnect: a
very brief red **Protection error / Schutzfehler** could appear while the worker
was intentionally moving between the verified VPN-down/firewall-present and
verified firewall-released states. The security outcome was correct, but a
background three-second status poll could sample an intermediate transaction
state. The GUI now suppresses only non-forced periodic status polls while an
intentional disconnect transaction is in progress. Success/failure still forces
an immediate status refresh from the committed verified outcome. This is UI
state polish only; it does not relax firewall checks or change helper behavior.

The authoritative unprivileged Stage-8C.2/release regression gate is green on
this A8 source after the release-copy, About-credit, and intentional-disconnect
status-poll changes. **Stage 8C.3A is therefore functionally closed.**

**Current release boundary:** the next work is the final Stage 8C.3
release-candidate functional/UI regression, followed by the Stage 8D release
freeze/build/tag gate. Do not reopen the NetworkManager route-only IPv6
approaches.


### Stage 8C.3A.9 pre-RC full-source audit follow-up (2026-08-08)

Before the final Stage 8C.3 release-candidate user regression, a fresh full-source
archive was reviewed as one coherent tree rather than as another incremental
patch. Generated `.venv`, `build`, `dist`, cache and `.git` data were intentionally
excluded from the review archive; source, tests, helper, packaging, workflows,
documentation and retained test evidence were present.

The audit found one real recovery defect in `KillSwitchSessionClient.open()`. The
client cached the broker's validated `ready` frame and returned it unconditionally
on later `open()` calls. `is_open` already knew how to detect that the underlying
privileged broker process had exited, but `open()` did not consult that liveness
state. A broker that died, reached its request limit or expired after its idle
timeout could therefore leave a cached client that repeatedly attempted later
normal IPv6-guard work against a dead session. The most visible case was an
intentional normal-VPN disconnect: the VPN/guard lifecycle remains fail-closed,
so this was **not an IPv6 or direct-network leak**, but the user could be left with
the IPv6 guard retained and need a later recovery/restart instead of getting a
fresh authorization session automatically.

The client now reuses a cached session only while the transport still reports it
alive. If the cached broker is dead, `open()` discards the stale ready/request
state, best-effort closes the dead transport, reruns the fixed executable
preflight and starts a fresh authenticated broker session. The existing live
session idempotence behavior remains unchanged, so a healthy broker does not
create a second Polkit/pkexec authorization. A new client regression test kills
the fake broker between two `open()` calls and requires the second call to start
a new broker with a new PID; the pre-existing idempotence test still requires one
start for a healthy session.

The broader audit rechecked the privileged helper/install boundary, crash-state
files, NetworkManager verified-state handling, normal IPv6 guard/full Kill Switch
mutual exclusion, nftables fail-closed ordering, WireGuard config creation,
credential/log boundaries, AppImage build provenance and application quit paths.
No second fail-open/leak-class defect was found in this pass. This does not prove
absence of all bugs; the final real-user RC regression remains mandatory.

Release-hygiene notes intentionally **not** changed by this corrective patch:
`CHANGELOG.md` and AppStream currently carry the provisional 0.6.0 date
`2026-08-07`; Stage 8D must set both to the actual publication date before the
release commit/tag. The GitHub workflows also still use floating major Action
refs. Because the release workflow has `contents: write`, Stage 8D should pin the
exact reviewed Action revisions before the public tag/release rather than leave
that supply-chain boundary mutable. Fully hash-pinning Python dependencies is a
larger reproducibility follow-up and can remain post-0.6.0.

The complete authoritative unprivileged release gate passed in the isolated
review environment after this fix. Because production session logic changed, that
container result is not the release authority. **Before Stage 8C.3 RC testing, rerun
`bash tools/release-stage8c2-self-test.sh` on the real Bazzite development host.**
If it is green, build the RC through the normal packaging path and proceed with
the full Stage 8C.3 functional/UI regression. Record the real-host result here
before the release freeze.

### Stage 8C.3B.1 clean-slate first-run + A10 RC polish (2026-08-08)

The A9 broker-session recovery change passed the authoritative
`tools/release-stage8c2-self-test.sh` gate on the real Bazzite development host.
The release test, Stage-7D, Stage-8B, Stage-8B.2 and Stage-8C.2 hardening gates
all ended green. A fresh A9 development RC was then built through
`tools/release-stage8c2-packaging-host-test.sh`; the AppImage and portable
SHA-256 sidecar verified, runtime/license/provenance inspection passed, and the
extract-and-run version smoke test reported `0.6.0`.

Before functional RC testing, the host was deliberately returned to a
first-install state: user config/cache/state absent, no PIA Bazzite
NetworkManager profile, neither production nftables table present, and no
installed `/usr/local/libexec/pia-bazzite` helper. The resulting first run was
clean. The credentials dialog appeared without stale state, normal disconnected
UI/tray behavior was correct, and the first normal-VPN connection correctly
detected the missing packaged helper. The intended installation confirmation
appeared, Polkit/helper installation completed, the subsequent protected
firewall authorization/session proceeded without an app restart, and the VPN
connected smoothly.

Two **non-security, non-release-architecture polish findings** were recorded
from that real first-run flow before continuing the RC matrix:

1. The helper install/update confirmation copy was correct but displayed as one
   dense paragraph. Both German and English install/update messages now contain
   explicit paragraph breaks separating (a) what the root-owned component does,
   (b) installation/update behavior and its non-effect on current VPN/firewall
   state, and (c) why two administrator prompts can legitimately appear.
2. The Live Log could show two identical `public network information refreshed`
   lines a few seconds apart. Multiple automatic lifecycle/status refreshes are
   allowed to reconfirm public network information, so no network refresh path
   was removed. `refresh_public_info()` now suppresses only an automatic log
   line when the newly returned `PublicNetworkInfo` is identical to the value
   already displayed. An explicit user-triggered refresh (`show_errors=True`)
   still logs every completed result. Disconnect still clears `public_info`, so
   a later connection logs its endpoint normally.

Regression coverage now requires paragraph breaks in both install and update
messages for both languages and requires the automatic duplicate-log guard in
the public-info refresh path. Focused Stage-8C.3A/8C.2/IPv6-lifecycle regression
coverage is green in the review environment after A10.

**Current release boundary:** A10 changes user-visible RC behavior, so apply it,
rerun the authoritative Bazzite Stage-8C.2 self-test, rebuild the RC AppImage,
and repeat the clean-slate helper-install/first normal-connect observation
before proceeding to the remaining Stage 8C.3B normal-VPN, server-switch, Kill
Switch, recovery, tray and shutdown matrix. These A10 changes do not alter
firewall/helper privilege semantics or the proven IPv6 containment architecture.



### Stage 8C.3B.2 real RC network/recovery matrix + A11 blocking-crash fix (2026-08-08)

After A10 passed the real-host authoritative self-test, the RC regression continued
against the rebuilt AppImage. The following real Bazzite observations passed:

- **Normal VPN / Kill Switch OFF:** NetworkManager policy routing selected
  `default dev piabazzite table 51960`; public IPv4 used the PIA exit, the small
  `pia_bazzite_ipv6_guard` table was active and counted blocked IPv6 traffic, the
  full `pia_bazzite_killswitch` table was absent, and `curl -6` could not escape.
- **Normal intentional disconnect:** the VPN and small guard disappeared, normal
  public IPv4 returned, and native public IPv6 returned immediately with no red
  protection-error flicker.
- **Normal server switch:** the new PIA exit became active, IPv6 remained blocked,
  and Main/Tray stayed in the correct blue VPN-only state.
- **Session Kill Switch connect:** the full production table contained only the
  expected physical-interface, endpoint and tunnel allows plus the final
  `block-outside-vpn` reject; the small IPv6 guard did not coexist; IPv4 used PIA,
  IPv6 was blocked, and Main/Tray were green.
- **Forced VPN loss:** the UI moved through the orange safely-blocked state, the
  firewall reject counter increased, all previously reachable ordinary paths
  were verified blocked, endpoint allows were retargeted under lock, and the VPN
  recovered to green in about two seconds.
- **Protected server switch:** the old tunnel was stopped while the lock remained
  active, blocked-path verification passed before the new endpoint was admitted,
  the new tunnel was started and jointly postchecked, and the new Austrian PIA
  exit was reached without any red state.
- **Intentional disconnect with Kill Switch:** VPN-down was followed by verified
  firewall release; both production tables were absent and normal IPv4 + IPv6
  returned. KDE/NetworkManager temporarily continued to report `limited`
  connectivity, then cleared it on its next connectivity check. README must
  explain that this desktop indicator is expected while the Session Kill Switch
  blocks NetworkManager's own direct connectivity probe and may lag briefly
  after release.
- **Connected-state SIGKILL:** killing only the AppImage GUI left the WireGuard
  profile and production firewall active; public IPv4 still used PIA and IPv6
  remained blocked. On restart, after Polkit authorization, the exact surviving
  VPN/firewall/recovery record was verified and adopted safely back to green.
  A short red/unverified UI state before authorization is intentional: the new
  GUI must not claim verified protection before the privileged state is checked.

The next adversarial test deliberately killed the GUI during the very short
`protected-blocking` phase after an externally forced VPN loss. **The security
boundary itself remained fail-closed**: normal networking stayed blocked and the
external Stage-7D Emergency Reset later restored the host in VPN-first order.
However, the restarted GUI did not recover cleanly and this is a release blocker.

Observed failure chain:

1. At startup the full Kill Switch crash-recovery check began and waited for the
   Polkit-authenticated helper session.
2. In parallel, `_first_start()` launched the normal server-list refresh. Because
   the host was intentionally in a blocking state, DNS/network access to
   `serverlist.piaservers.net` correctly failed.
3. The resulting modal `No internet connection` QMessageBox appeared while the
   Polkit authorization was pending, obscuring/interfering with the authentication
   flow. The user could not complete the intended prompt before the helper's
   120-second timeout.
4. Startup reconciliation then failed with `HelperTimeoutError`. A later read-only
   status recheck correctly confirmed the production firewall was still present,
   but the app no longer had the recovered baseline/session needed for a normal
   release. The quit path correctly refused to close while the lock remained.
5. One dialog exposed a separate copy bug: `error.kill_switch_quit_blocked.title`
   had no translation entry and was shown literally.
6. The documented `kill-switch-crash-stage7d-emergency-reset.sh` was used manually
   and successfully restored normal networking; the running app then verified
   the firewall absent and cleared its stale protection error.

**A11 corrective design:**

- The first server-list network request is now gated behind full Kill Switch
  startup reconciliation whenever the preference is enabled or a crash-recovery
  record exists. Cached regions remain available while safely blocked. The first
  network refresh is released only when the host is verified connected or the
  lock is verified absent; a successful protected reconnect or Emergency Reset
  also releases the deferred refresh. This removes the modal network-error/Polkit
  race without weakening any firewall or helper check.
- A new integrated **Help -> Emergency Reset...** path uses the already-audited
  fixed installed helper action but wraps it in an explicit unprivileged
  VPN-first coordinator. It queries NetworkManager, stops the PIA profile if
  needed, independently re-queries and refuses to touch the firewall if the VPN
  is still active or its state cannot be verified, then invokes only the fixed
  helper `emergency-reset` action. The helper must return a structurally verified
  `disabled`/table-absent status before the fixed crash-recovery pathname is
  discarded. Any failure remains fail-closed and never claims successful release.
  The Kill Switch preference remains enabled for the next connection.
- The Emergency Reset confirmation explicitly says it is last-resort recovery,
  that normal networking can return immediately after release, and that no other
  firewall tables are modified.
- `error.kill_switch_quit_blocked.title` now has matching English/German copy;
  related recovery messages point users to the integrated Help action.
- README/0.6.0 release notes now document both the integrated Emergency Reset and
  KDE/NetworkManager's expected temporary `Limited connectivity` indication.
- New unit/static regressions require VPN-down verification before the helper
  reset, helper reset before recovery-record cleanup, no firewall reset when VPN
  cannot be proven down, matching EN/DE Emergency Reset copy, and deferred initial
  server refresh during full Kill Switch startup reconciliation.

**Required next gate:** run the full authoritative unprivileged Stage-8C.2 gate
on the real Bazzite host, rebuild the RC AppImage, then repeat the exact
blocking-state SIGKILL test. Expected result after A11: no server-list network
error is launched while the host is safely blocked and awaiting Polkit; after
authorization the old production table/recovery record is adopted as orange
`Safely blocked`, the cached server selection remains usable, and protected
reconnect returns to green. Also exercise **Help -> Emergency Reset...** once in
a deliberately safely-blocked state and verify VPN-down -> firewall absent ->
normal IPv4/IPv6 restored. Do not continue toward Stage 8D until both paths pass.

### Stage 8C.3B.3 A11 blocking-state retest + A12 false-error fix (2026-08-08)

The rebuilt A11 RC was retested against the same real Bazzite adversarial case:
the VPN was externally stopped, the crash-recovery journal reached
`protected-blocking`, and only the AppImage GUI was killed with SIGKILL while the
full production Kill Switch remained active.

A11 fixed the original release blocker. On restart, no PIA server-list network
request or modal `No internet connection` error raced the Polkit prompt. After
authorization, the host was visibly and internally adopted as the expected orange
**Safely blocked** state: VPN down, exact verified production firewall route still
active. This proves the deferred initial server refresh works for the real blocked
startup path.

The retest exposed a smaller GUI-only defect immediately after that successful
adoption. `CrashRecoveryVerifier` correctly returned `ADOPT_BLOCKING` with reason
`The VPN is down and the exact verified firewall route remains active.`, the GUI
committed the blocking recovery record and displayed `Safely blocked`, but the
post-success dialog gate still showed the generic red startup-recovery error for
all dispositions other than `NO_RECOVERY` / `CLEAR_STALE_RECORD` unless the adopted
state was connected. In other words, the protection and recovery result were
correct while the dialog falsely described the successful `ADOPT_BLOCKING` result
as a failure.

**A12 correction:** the generic startup-recovery error dialog is now restricted to
non-adopted refusal dispositions. Both `ADOPT_CONNECTED` and `ADOPT_BLOCKING` are
successful reconciliation outcomes and therefore never produce that failure
message. Connected adoption may still refresh public network information; blocking
adoption remains offline and keeps the cached region list until a safe reconnect or
verified release permits network refresh. No NetworkManager, nftables, helper,
firewall, route, crash-record or privilege semantics changed in A12.

A regression test now requires the startup-recovery error gate to exclude every
`decision.adopted` outcome. The focused Stage-8C.3B crash-recovery polish test is
green in the review environment after the fix.

**Next real-host gate:** apply A12, run `bash tools/release-stage8c2-self-test.sh`,
rebuild the RC AppImage, and repeat only the final blocked-startup adoption portion
of 9B. Expected result: after Polkit authorization the app goes directly to orange
`Safely blocked` with no server-list error and no generic red recovery-error dialog;
then the protected reconnect returns to green. After that, exercise the integrated
**Help -> Emergency Reset...** path once from a deliberately safely-blocked state.

**Collected final UX item (do not mix into the current blocker retest):** if an
automatic startup protection check genuinely times out or is refused, the failure
dialog should directly offer a retry and the same safe integrated Emergency Reset
entry point instead of requiring the user to discover it under Help. Emergency
Reset must remain explicit and never automatic; its audited VPN-down verification
and fail-closed firewall-release ordering stay unchanged. The Help-menu action
should remain available as an independent last-resort path.


### Stage 8C.3B.4 real blocking recovery / Emergency Reset / shutdown passes + A13 idle-start authorization fix (2026-08-08)

The rebuilt A12 RC passed the shortened real-host blocking-crash retest. After
SIGKILL in `protected-blocking`, restart presented an unobstructed Polkit prompt;
authorization adopted the exact surviving firewall/recovery route directly as
orange **Safely blocked** with no false generic recovery-error dialog. Manual
protected reconnect then verified the retained lock, proved ordinary IPv4/IPv6
and direct DNS paths blocked, retargeted the endpoint allowlist under lock,
reactivated the existing NetworkManager WireGuard profile, jointly postchecked
VPN + firewall, saved the connected recovery state, and returned to green. Only
after that safe reconnect did the deferred server-list/public-info refresh run.
This closes RC block 9B.

The integrated in-app Emergency Reset was then exercised from the intended
safely-blocked state. It completed without the external Stage-7D reset script.
Post-reset host verification showed no active PIA NetworkManager connection, no
`pia_bazzite_killswitch` table, no `pia_bazzite_ipv6_guard` table, and restored
normal public IPv4 plus native public IPv6. This closes RC block 10 and proves a
non-terminal user can deliberately recover normal networking from the fail-closed
state. The product copy must remain explicit that the reset keeps traffic blocked
until the VPN-down condition and firewall release are verified, but **after the
reset completes the normal connection is no longer VPN-protected and the user's
real public IP may be visible**. Never promise continued public-IP protection
after a successful reset.

RC block 11 also passed on real Bazzite: window close/minimize-to-tray, tray
reopen/menu behavior, VPN + Kill Switch continuation while the window is hidden,
and all configured quit behaviors behaved correctly. In particular, a remembered
`leave VPN connected` preference was still refused while the Session Kill Switch
was active. KDE/Plasma may show its own repeated system-tray minimization hint on
each application start; the same behavior occurs with other applications and is
considered desktop-environment behavior rather than a PIA Bazzite defect.

During RC block 12 (settings persistence), a new startup UX defect was isolated:
when the Session Kill Switch **preference** was remembered as enabled but the VPN
was cleanly disconnected and no production firewall should exist, every fresh app
start still entered full startup reconciliation. The UI was red until Polkit
authorization completed and the user was asked for an administrator password on
every launch. Disabling the Kill Switch preference removed the prompt, confirming
that `_startup_kill_switch_reconciliation_required()` was incorrectly treating
`feature_enabled` itself as proof that privileged recovery might be needed. This
is not a leak/fail-open issue, but it is unacceptable normal-start UX and a false
protection-error presentation.

**A13 correction and safety boundary:**

- A remembered Kill Switch preference by itself no longer triggers startup
  Polkit/reconciliation. Clean disconnected startup may render the non-protective
  `ARMED` state without a privileged helper status; `ARMED` makes no claim that a
  firewall is currently protecting traffic. The helper is authorized when a
  protected connection is actually requested.
- Startup reconciliation is now triggered by either the existing crash-recovery
  record or a separate persisted `kill_switch/reconciliation_required` marker.
- The marker is written **before** the protected-connect worker can arm the
  production firewall. This deliberately preserves detection of the narrow crash
  window between firewall mutation and creation of the richer connected
  crash-recovery record; simply changing the old gate to `record exists` would
  have regressed that fail-closed recovery property.
- The marker remains set while production Kill Switch protection may exist. It is
  cleared only on paths that have independently verified safe release/table
  absence (normal protected disconnect/release cleanup, successful preference
  authorization with table absent, startup reconciliation proving no live table,
  or the verified integrated Emergency Reset). Exact adoption explicitly keeps
  the marker set. Refused/failed reconciliation does not clear it.
- `_disconnected_kill_switch_may_block()` no longer treats an absent cached helper
  status as blocking when there is no error and no persisted reconciliation hint.
  A real helper error, a present cached table, a recovery record, or the pre-firewall
  marker still keeps the UI/network paths conservative.
- The initial server refresh therefore runs normally for a clean disconnected
  `ARMED` start, while crash-surviving states still defer network I/O until
  reconciliation/release exactly as required by A11.

Regression coverage was updated so the Stage-7C startup test requires automatic
reconciliation from persisted recovery hints rather than from the preference
alone. Stage-8C.3B coverage additionally requires the pre-firewall marker to be
set before the protected worker/orchestrator, verifies marker clearing/retention
boundaries, and requires the clean idle `ARMED` path not to be classified as a
possible disconnected lock.

**Required A13 real-host check before resuming block 12:** apply A13, run the
authoritative `bash tools/release-stage8c2-self-test.sh`, rebuild the AppImage, and
perform two ordinary launches while VPN is disconnected and the Kill Switch
preference remains enabled. Both launches must stay neutral/armed (not red), must
not request Polkit, must load the normal server list, and must leave the preference
checked. Then connect once with Kill Switch enabled: Polkit may be requested at
that point because a privileged firewall mutation is actually being requested;
the connection must still reach green. Disconnect normally and launch once more
to prove the marker was cleared by verified release. After that, resume block 12
settings persistence.

**Collected final-polish items remain deferred until functional regression is
complete:** rename the German Help action away from the mixed/technical
`Notfall-Freigabe (Emergency Reset)...` wording (preferred direction:
`Kill-Switch-Schutz zurücksetzen...`, English `Reset Kill Switch Protection...`);
show that Help action only when it is operationally relevant (orange safely
blocked, or a red/unverified state where a production firewall is known/present);
remove the now-unnecessary `use only when Safely blocked` sentence from its
confirmation; clearly state that normal non-VPN networking and the real public IP
may become visible after success; and on a genuine startup-recovery timeout/refusal
offer both retry and the same explicit verified reset directly in the failure
dialog. Emergency Reset must never run automatically.

### Stage 8C.3B.5 remaining real-host RC passes + A14 final polish (2026-08-08)

After the A13 idle-start correction, the real Bazzite RC passed the remaining
functional/UI regression blocks:

- **Block 12 — settings persistence:** language, fixed theme, Live Log visibility,
  remembered Kill Switch preference, quit policy and stored PIA credentials all
  survived a full app restart. A clean disconnected `ARMED` launch no longer
  requested Polkit or flashed a false red state; normal protected connect still
  requested authorization only when privileged firewall work was actually needed.
- **Block 13 — single instance:** starting the AppImage a second time never created
  a second controller/GUI/tray instance, both while disconnected and while protected
  green.
- **Block 14 — tray disabled:** with the tray disabled, closing the window correctly
  uses the real quit flow instead of hiding an unreachable background process.
  Protected quit policy still refuses `leave VPN connected` while the Session Kill
  Switch is active.
- **Block 15 — suspend/resume:** after Bazzite suspend/resume the NetworkManager PIA
  WireGuard profile and full Kill Switch remained active, public IPv4 remained the
  PIA exit, IPv6 remained unavailable outside the tunnel, the UI remained green,
  and no unnecessary recovery/Polkit cycle was triggered.
- **Block 16 — physical network loss/recovery:** disabling Wi-Fi made the physical
  interface unavailable while NetworkManager correctly continued to report the
  configured WireGuard profile as administratively active. A delayed sample showed
  the WireGuard handshake ageing past two minutes, while the Kill Switch remained
  active and both IPv4 and IPv6 public-network probes failed. No fail-open occurred.
  Re-enabling Wi-Fi allowed the existing WireGuard profile to resume normally.
  Green continues to mean **VPN configuration active + Kill Switch active/verified**,
  not a synthetic guarantee that the remote endpoint is reachable in the current
  second. No new HTTP/ping/handshake-age watchdog is added for 0.6.0.
- An additional real-world NetworkManager/KDE test deliberately disconnected the
  `PIA Bazzite` WireGuard profile from the desktop network UI. The app detected the
  tunnel loss, persisted `protected-blocking`, verified all ordinary IPv4/IPv6/DNS
  paths blocked, retargeted the protected route under lock, rebuilt the existing
  profile and jointly verified VPN + firewall before returning to green.
- **Block 17 — Polkit cancellation:** cancelling authorization while enabling the
  Kill Switch left the preference off, VPN down and no production firewall/IPv6
  guard. Cancelling authorization during a protected connect left the remembered
  preference enabled but did not start the VPN and did not create a Kill Switch
  table. This is safe; the only RC finding was overly severe red/error presentation
  for a deliberate user cancellation.
- **Block 18 — offline start/recovery:** clean disconnected startup with Wi-Fi off
  stayed in `VPN & Kill Switch ready`, required no Polkit and remained usable.
  Server-list loading correctly failed because DNS/networking was unavailable.
  Returning Wi-Fi does not add a new automatic network-state watcher in 0.6.0;
  explicit server-list refresh immediately restored all locations/pings and a
  subsequent protected connection reached green. Manual refresh is accepted as the
  deliberate low-complexity release behavior.
- **Block 19 — final UI/operation sanity:** search/filter clearing, location
  selection, server-list refresh, ping refresh, public-IP manual refresh, menus,
  About/version, DE/EN switching, theme switching, Live Log copy/save/clear, links,
  and one final normal protected connect/disconnect cycle all passed.

This closes the functional Stage-8C.3B RC test matrix. The remaining source change
is the deliberately batched **A14 final polish**, built from the user's complete
current A13 archive rather than an older patch baseline.

**A14 final-polish scope:**

1. Rename the mixed/technical Help command to German
   `Kill-Switch-Schutz zurücksetzen…` and English
   `Reset Kill Switch Protection…`. User-facing reset copy/logs/docs use the
   product wording; internal module/function names may retain `emergency_reset`.
2. Hide the Help reset command by default and show it only when a production
   Kill Switch firewall is actually known present in a disconnected state, or in
   a red/unknown-network state where that table is known present. It is hidden in
   ordinary gray/armed, blue VPN-only and healthy green protected states. Busy
   operations keep a relevant action disabled rather than making it executable.
3. Remove the old `use only when Safely blocked` sentence from reset confirmation.
   The confirmation now states the safety order explicitly: VPN is stopped/verified
   first while the Kill Switch remains active; only then is PIA Bazzite's fixed
   table removed. It also explicitly warns that after successful release normal
   networking is **outside VPN protection and the real public IP may be visible**.
4. Genuine startup protection-reconciliation failure/refusal now uses an actionable
   dialog with **Retry protection check**, **Reset Kill Switch Protection…**, and
   Cancel. Retry schedules the same read-only reconciliation again. Reset only opens
   its independent explicit confirmation dialog; it never executes automatically.
   The audited VPN-first reset backend is unchanged.
5. Deliberate Polkit cancellation/denial in the two safe pre-mutation cases tested
   in block 17 (enabling the preference and protected-connect authorization) is
   recognized through the exception cause chain and presented as a neutral
   `Authorization not granted` information outcome rather than a critical red
   application failure. The VPN/firewall unchanged guarantee is stated only in
   these paths where authorization fails before privileged mutation.
6. German `Serverliste neu laden` becomes `Serverliste aktualisieren`; English
   becomes `Refresh server list`. Public shortcut documentation matches.
7. The long IPv6-protection fact tooltip now contains deliberate line breaks in
   both languages so Plasma/Qt does not render a monitor-wide single-line tooltip.
8. README and 0.6.0 release notes use the new reset product name and explicitly
   document the post-reset real-public-IP consequence.

A14 adds `tests/release/test_stage8c3b_final_polish.py` and updates the existing
Stage-8C.3B recovery-polish static assertion for the new actionable startup dialog.
The authoritative unprivileged
`bash tools/release-stage8c2-self-test.sh` passes locally after A14, including
translation parity (**475 EN / 475 DE**) and all inherited Stage-7D/8B/8B.2/8C.2
gates. This does **not** replace the required real Bazzite/AppImage check.

**Required next step:** apply A14 on the current A13 project, run the authoritative
self-test, rebuild the 0.6.0 AppImage with
`bash tools/release-stage8c2-packaging-host-test.sh`, then perform only a focused
final-polish host check: menu visibility/name in gray/green/orange/red-known-lock
states as practical; reset confirmation/public-IP warning; one Polkit cancellation
dialog; wrapped IPv6 tooltip; server-list wording; and, if practical, exercise the
startup-recovery failure dialog's Retry/Reset buttons without weakening the live
firewall. If clean, proceed to **Stage 8D release freeze / final metadata date /
workflow SHA pinning / final AppImage + SHA-256 / clean Git state / GitHub release
and tag `v0.6.0`**. Avoid starting a new broad regression matrix unless A14 exposes
a functional/security regression.

### Stage 8D release freeze (2026-08-08)

The focused real-host A14 polish check passed on the rebuilt Bazzite AppImage. The
final labels/menu visibility, wrapped IPv6 tooltip, neutral Polkit-cancellation
presentation, normal protected connect/disconnect smoke cycle and About/version
presentation were accepted. Stage 8C.3B is therefore closed; do not reopen a broad
regression matrix unless the freeze itself exposes a functional/security problem.

The 0.6.0 release metadata is now frozen for publication on **2026-08-08**:

- `CHANGELOG.md` and AppStream both use the final 2026-08-08 release date.
- Changelog/AppStream reset wording matches the A14 product wording
  **Reset Kill Switch Protection**; historical/internal Stage-7 `Emergency Reset`
  names remain unchanged where they describe those test tools/stages.
- Runtime, desktop metadata, release notes and workflow release body remain pinned
  to version `0.6.0` / tag `v0.6.0`.
- Public GitHub documentation remains English; DE/EN runtime localization remains
  intentional.
- Every third-party GitHub Action used by CI/release is pinned to the exact reviewed
  commit selected for its existing major-version line at freeze time:
  `actions/checkout` v4.3.1 -> `34e114876b0b11c390a56381ad16ebd13914f8d5`,
  `actions/setup-python` v5.6.0 -> `a26af69be951a213d495a4c3e4e4022e16d87065`,
  `actions/upload-artifact` v4.6.2 -> `ea165f8d65b6e75b540449e92b4886f43607fa02`, and
  `softprops/action-gh-release` v2.6.2 -> `3bb12739c298aeb8a4eeaf626c5b8d85266b0e65`.
  The release workflow retains `contents: write` because it must publish the GitHub
  release; immutable action pins bound that privileged workflow to reviewed code.
- The authoritative Stage-8C.2 packaging-hygiene test now asserts the final release
  date and rejects mutable/non-reviewed external Action refs.

**Release procedure from this freeze:** apply the Stage-8D freeze archive over the
current tested A14 tree, run `bash tools/release-stage8c2-self-test.sh`, review the
Git diff, commit the exact freeze tree, and ensure `git status --short` is empty.
Build the final local AppImage only from that committed clean tree if another local
sanity artifact is desired. The public release asset should be produced by the
pinned GitHub release workflow from the exact `v0.6.0` tag commit; its workflow
verifies the tag/version match, resets to `GITHUB_SHA`, builds the AppImage, smoke
tests it, verifies/regenerates the SHA-256 sidecar, uploads both artifacts, and
publishes `RELEASE_NOTES_0.6.0.md`.

After the freeze commit is pushed and CI is green, create/push tag `v0.6.0`. Do not
retag a different commit. Verify the resulting GitHub release contains exactly the
expected `PIA-Bazzite-0.6.0-x86_64.AppImage` and its `.sha256` sidecar, then perform
one final download/checksum/version smoke check of the published asset.

### Post-release 0.6.0 external review and documentation clarification (2026-08-09)

An independent post-release code review reported no release-blocking functional or
security defects. Two points were investigated:

- **Session Kill Switch reboot scope:** the reviewer correctly highlighted that
  the runtime `nftables` protection is not persistent across a full reboot, kernel
  crash or power loss. This was already documented under README limitations, but
  the boundary is important enough to surface more prominently. `README.md` now
  contains an explicit `Kill Switch scope` callout: fail-closed protection survives
  tunnel/GUI failure while the kernel remains running, but it is not an early-boot
  firewall and is not active again after boot until PIA Bazzite runs and activates
  the Kill Switch. This is a documentation-only post-release clarification and does
  not change 0.6.0 runtime behavior.
- **Helper checksum-before-import concern:** the reviewer noticed that
  `helper/pia_bazzite_kill_switch_helper/installed_entry.py` has package imports at
  module scope while its own `verify_installation()` call occurs later in `main()`.
  On re-checking the actual production launch path, this is already protected by
  the standalone installed bootstrap
  `helper/pia-bazzite-kill-switch-helper-installed`, which is installed as the fixed
  `/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper`. That bootstrap
  uses only the standard library, validates the fixed root-owned installation and
  checksum manifest in `_verify_installation()`, and only **after that** imports
  `pia_bazzite_kill_switch_helper.installed_entry`. The invariant is explicitly
  covered by
  `tests/polkit/test_installed_helper.py::InstalledFilesStaticTests::test_launcher_verifies_before_importing_installed_package`.
  Therefore this is **not** an outstanding 0.6.1 hardening defect in the released
  production path. Preserve this pre-import bootstrap boundary in future helper
  refactors.

Release policy after 0.6.0 remains conservative: do not create 0.6.1 solely for
this documentation clarification. Accumulate real bug fixes/hardening changes and
ship a maintenance release when there is enough reason to do so.

---

## 20. HANDOFF maintenance rule

Update this file whenever a future release changes architecture, support status, privileged boundaries, firewall/recovery behavior, user-visible safety semantics, verified host behavior, release procedure, or a design decision that a later developer/ChatGPT instance would otherwise have to rediscover.

Keep historical evidence when it explains why a current invariant exists, but always update the **Current release state**, **Source of truth**, **Known limitations**, **Future development stance**, and **Quick do-not-regress checklist** so old stage language cannot be mistaken for the present state.

- Stage 4B Auto-Connect startup execution is verified and frozen after the complete real-Bazzite matrix: preserve the one-shot startup gates, exact fixed/last target semantics, fastest-reachable-only dynamic resolution, recovery priority, and reuse of `connect_region()`. Stage 4C adds only login-autostart and tray/options presentation around that path; do not let it bypass Stage 4B safety gates. Remember that ordinary Auto-Connect with Session Kill Switch disabled may still require administrator authorization for the separate IPv6-only firewall guard.
