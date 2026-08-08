# PIA Bazzite — living project handoff

This file is a **living handoff**, not a release note. Update it after every
meaningful substage, architecture change, security decision, or roadmap change
so a future development session can continue without reconstructing decisions
from chat history.

## Current target

- Release target: **0.6.0**
- Expected working branch: `feature/session-kill-switch` (verify in Git; review
  archives intentionally do not contain `.git`)
- Current phase: **Stage 8C.3B release-candidate regression is functionally complete through RC blocks 1–19 on real Bazzite. A14 is the collected final UX/recovery polish pass; its unprivileged authoritative self-test is green and it now awaits real-host AppImage rebuild plus focused UI validation before Stage 8D release freeze.**
- Latest real-host milestone: **A13 passed the authoritative Bazzite self-test/rebuild and the remaining RC matrix passed through settings persistence, single-instance behavior, tray-disabled shutdown, suspend/resume, physical-network loss/recovery, external NetworkManager VPN disconnect/recovery, Polkit-cancel fail-safe behavior, offline start/manual refresh recovery, and final UI sanity.** No fail-open was observed. A14 changes only recovery UX/presentation, action visibility, authorization-cancel presentation, wording/tooltips, release docs, tests, and this handoff; it does not change the audited firewall/helper ordering.

## Proven before Stage 8C

The real 0.6.0 AppImage was built and its SHA-256 sidecar verified. Its embedded
helper bundle matched the manifest. Normal AppImage FUSE root-unreadability was
handled through private normal-filesystem staging. A missing helper installed
through explicit user confirmation + Polkit, an exact helper was reused without
reinstallation, and a deliberately outdated helper required an explicit update.

Stage 7 is the authoritative crash/recovery security foundation:

- Stage 7C.4: GUI SIGKILL persistence and automatic exact takeover passed; 50
  independent sentinel samples showed no direct fallback.
- Stage 7D: corrupt recovery record, unowned firewall lock, Emergency Reset and
  clean restart passed; 47 independent sentinel samples showed no direct
  fallback.
- Older 7C.1–7C.3 host experiments are retained as history/regression evidence;
  7C.4 is authoritative for process/transport takeover proof.

## Security invariants

1. Session Kill Switch is fail-closed.
2. Firewall protection is established before a protected VPN is started.
3. Firewall release is allowed only after VPN absence and the expected blocked
   path have been independently verified.
4. `unknown` NetworkManager state is never treated as `disconnected`.
5. Protected reconnect and protected server switch must never create direct
   fallback traffic.
6. GUI stays unprivileged; privileged nftables work is confined to the fixed
   helper boundary.
7. AppImage helper install/update must install exactly the verified payload;
   packaged mode must never downgrade to source-tree mode.
8. Crash-recovery records are hints, not authority. Adoption requires matching
   live helper, NetworkManager, route, firewall, and recovery state.
9. Emergency Reset stops the VPN before removing the fixed firewall table and
   cleans an untrusted recovery path only after verified host release.
10. Secrets (passwords, PIA tokens, WireGuard private keys) must not enter logs
    or release artifacts.

## Development workflow preferences

Keep these non-sensitive working conventions across future sessions:

- Prefer **one test too many rather than one too few**, especially around
  privilege boundaries, networking, recovery, AppImage packaging and release
  gates. Do not skip a host retest after changing security-sensitive production
  logic.
- Before preparing code updates, work from the **current project state/archive**
  instead of reconstructing or mixing old versions.
- Give **copy/paste-ready commands**, explicit paths and the exact PASS/output to
  expect; do not assume development-tool knowledge.
- Put generated update/archive artifacts in the user's **Downloads directory**
  (use `$HOME/Downloads` in commands; never hard-code a personal username into
  public project files).
- Treat a **full code audit before a major/final release** as part of the release
  process. Classify findings by release risk and avoid broad cosmetic refactors
  immediately before a security-sensitive release.
- Preserve privacy in public sources and release artifacts: no personal home
  paths, local usernames, credentials, tokens, private keys or other identifying
  development leftovers.
- Maintain this handoff **continuously after meaningful substages, security
  decisions, host-test results and roadmap changes**; do not wait for a chat to
  be near its context limit.

## User-visible Kill Switch states

- Neutral gray: VPN intentionally off; Kill Switch off / ready.
- Neutral gray: VPN intentionally off; Kill Switch enabled for next connection.
- Blue: VPN connected without Kill Switch.
- Green: VPN connected + verified Kill Switch protection.
- Orange: VPN lost; verified Kill Switch is blocking safely.
- Red: protection expected but cannot be guaranteed.

The manual read-only status action is named **“Schutzstatus neu prüfen”** in the
German UI.

## Stage 8 status and next steps

### 8C.1 — full code audit

Completed. Main release blockers identified: packaged-helper privilege-handoff
TOCTOU/downgrade risk, NetworkManager query failures being collapsed to
“disconnected”, and stale SECURITY documentation. Important hardening also
includes safe WireGuard-config creation, stricter PIA-response validation,
single-instance startup serialization, public-IP lookup privacy, CI/release
coverage and deterministic packaging hygiene.

### 8C.2 — current hardening

The first hardening slice addresses the release-sensitive audit findings without
a broad refactor:

- packaged helper privilege handoff now anchors authorization to the verified
  AppImage manifest digest, copies opened-and-hashed bytes into a root-owned
  private `/run` tree, and forbids packaged-to-source downgrade;
- NetworkManager query failure is `unknown`, never `disconnected`;
- WireGuard config output is created private (`0600`) from the first open and
  refuses unsafe targets;
- PIA values that form network/WireGuard configuration are validated before use;
- stale single-instance socket cleanup is serialized with a lock;
- automatic public-IP lookup while verified disconnected is removed and
  documented;
- stale Kill Switch security documentation is corrected;
- known personal development paths/legacy organization markers are removed from
  the public source tree and guarded by a release regression test.

Avoid a large `gui.py` refactor before 0.6.0. The unprivileged Stage-8C.2
self-test **passed on Bazzite**, and the real AppImage helper host gate was rerun
after the privilege-handoff changes and **passed again**: missing helper install,
exact-helper reuse and explicit outdated-helper update all succeeded.
The second 8C.2 packaging-hardening slice is implemented and awaits its final
Bazzite packaging-host proof: CI and release jobs use one authoritative
unprivileged gate; local release-mode Podman builds require a completely clean
Git tree and export only `HEAD`; the GitHub release job resets/cleans the tree
after tests before building; direct release builds reject dirty/mismatched source
identity; `appimagetool` 1.9.1 is SHA-256 pinned before execution; build
provenance is embedded in `BUILD_INFO.txt`; and the AppImage build generates an
inventory plus available license/notice files for the installed Python runtime
dependency graph, including PySide6/Qt material supplied by the wheel. Release
notes no longer expose internal Stage-8 wording. Run
`tools/release-stage8c2-self-test.sh` and then
`tools/release-stage8c2-packaging-host-test.sh`; only after both pass should
8C.3 begin.

### 8C.3 — release-candidate regression

Build the RC from the hardened tree and exercise normal VPN mode plus the
essential Kill Switch paths (connect/disconnect, protected switch/reconnect,
crash/takeover subset, tray/UI/log/language/theme smoke checks).

### 8D — final release gate

Freeze the release commit, build the exact AppImage, verify checksum and
metadata/notices, run the shortened final host gate, then tag the exact tested
commit as `v0.6.0` and prepare the GitHub release.

## Planned post-0.6.0 roadmap

The plan is intentionally flexible; no feature is promised until implemented
and tested.

- **0.7.x candidates:** server favorites, Auto-Connect, suspend/resume handling,
  and robust network-change handling.
- **0.8.x candidates:** trusted networks and an optional, carefully tested local
  LAN-access exception for the Kill Switch.
- **0.9.x candidate:** PIA port forwarding on supported regions.
- **Later / high risk:** per-app split tunneling. Treat this as a security/routing
  project comparable in complexity to the Kill Switch, not a small feature.
- **1.0.0:** reserve for a mature, stable overall product rather than using the
  number as a deadline for arbitrary feature accumulation.

After 0.6.0, consider splitting the very large GUI/controller module gradually,
and introduce/style-gate tools such as Ruff and optional type checking without
mixing a broad refactor into a security release.

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

Post-0.6.0 UX roadmap: add a real Options dialog once enough settings/features exist to justify it (Auto-Connect, trusted networks, LAN access, and related options are natural candidates).

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
- Options order: `Kill Switch verwenden` follows the `Beim Beenden mit aktivem
  VPN` submenu.
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
