# Changelog
All notable changes to PIA Bazzite are documented in this file.

## [0.7.0] - 2026-08-13
### Added

- Added the 0.7 Stage 6B tabbed Options/behavior polish: the fixed-size Options dialog is reorganized into General, Connection, and Network & Privacy tabs and adds three meaningful preferences with existing-behavior defaults — security/error notifications, server-switch confirmation, and public IP/location display. PIA Bazzite notifications deliberately avoid duplicating normal Plasma/NetworkManager connect/disconnect messages and are limited to important background Kill-Switch or Auto-Connect failure events. The repetitive close-to-tray hint notification is removed. Disabling public IP/location also suppresses the associated external provider lookup and disables that provider selector until re-enabled. The one-line `▶ Streaming-optimized location` marker legend is restored while the virtual-location marker keeps its short physical-location explanation. Follow-up KDE polish removes redundant in-tab group titles and, after real Plasma exposed `QFormLayout` wrapping/overlap in the fixed 560 px dialog, uses a two-column grid with natural labels, right-aligned fixed-width selectors, and full-width checkbox rows. The third tab renders the requested `Netzwerk & Datenschutz` / `Network & Privacy` via escaped `&&` mnemonic text. Tray tooltip first lines use `PIA Bazzite: …`; Qt's `QSystemTrayIcon` exposes only one tooltip string and maps it to the StatusNotifierItem title with no separate subtitle, so the current backend intentionally keeps the detail line as a plain-text fallback rather than replacing the tray stack solely for typography. Real Bazzite visual/interaction confirmation passed, including 125% and 150% Plasma scaling during the release regression.
- Added the 0.7 Stage 6A UI/search/filter polish: the German Tools menu is now `Extras`, the compact Main window is 50 px narrower while Live Log keeps its diagnostic width, and the server search field gains an integrated All/Normal/Virtual/Streaming filter. Text search now understands the hidden marker meanings in both DE/EN and combines them with location-name tokens. The non-obvious virtual-location marker gets one short physical-location explanation; Stage 6B restores the Streaming marker's one-line legend without adding a redundant explanatory sentence. Fastest/Off/Quit mode/action icons are neutral/monochrome, gold is reserved for actual favorite status, and inactive favorite stars use stable QIcon modes so selection no longer changes every empty star's gray level. Focused Stage 6A regression coverage, the project self-test, the authoritative unprivileged release gate, and real Bazzite visual confirmation all pass.
- Added and verified the 0.7 Stage 5A physical-network state detection: PIA Bazzite now watches NetworkManager underlay changes separately from the administratively active WireGuard profile. `nmcli monitor` is used only as a fast event trigger; localized monitor text is never parsed, and every event is reconciled through numeric NetworkManager device state with a 3-second fallback poll. If Wi-Fi/Ethernet disappears while the VPN profile stays active, verified Session Kill Switch protection is presented Orange with explicit network-unavailable copy, normal VPN mode becomes neutral Grey instead of stale Blue, Red protection errors keep priority, public-network fields are suppressed, and server-changing controls are disabled until the underlay returns. Real Bazzite Wi-Fi loss/recovery passed in both modes: Green→Orange→Green with Session Kill Switch protection retained, and Blue→Grey→Blue in normal VPN mode with the IPv6-only guard retained. Stage 5A intentionally adds no new reconnect algorithm, delayed Auto-Connect, server-list auto-refresh, or handshake/HTTP watchdog.
- Added and verified the 0.7 Stage 4C login-autostart/tray polish: Options can create/remove PIA Bazzite's own user XDG autostart entry without administrator privileges. AppImage autostart uses the original `APPIMAGE` path instead of the temporary mount, source runs use the active Python interpreter plus `main.py`, and the generated entry launches with an internal `--autostart` flag. Login autostart stays hidden when the tray is actually enabled and falls back to the main window if the tray is disabled/unavailable; both paths passed real Bazzite login testing, and a duplicate autostart invocation does not raise an already-running instance. The tray root now uses desktop-theme icons (with neutral vector fallbacks) for connect/disconnect, server selection, Favorites, Show, and Quit; the disabled status row remains icon-free and favorite child rows no longer repeat gold stars. Real Bazzite testing also verified a dry `--autostart` launch and a full reboot/login XDG-autostart path with Auto-Connect. The Auto-Connect selector popup always opens scrolled to its first row; its special modes are grouped first as neutral-icon `Off`, neutral-icon `Last selected location`, then the neutral Fastest action, followed by gold-starred favorites without a redundant Favorites heading and finally the normal ping-sorted server list. Final real-Bazzite visual verification passed for this selector presentation, so Stage 4C is frozen.
- Added and verified the 0.7 Stage 4B Auto-Connect startup execution: after first-run credentials, the initial fresh server/ping refresh, and both Kill-Switch/IPv6-guard startup reconciliation gates have safely settled, the stored Auto-Connect preference resolves to the exact last/fixed region or the current fastest reachable region and reuses the existing `connect_region()` path. Existing VPN/recovery states take priority, missing fixed targets never fall back silently, failed initial region refresh does not trigger a delayed connection, and each app start can launch Auto-Connect at most once. The complete real-Bazzite matrix passed for Off, Last selected, Fastest, fixed ordinary/favorite targets, existing-VPN adoption, Session Kill Switch startup, and normal VPN mode. Normal mode may still request administrator authorization because its separate IPv6-only firewall guard is privileged leak prevention even when the Session Kill Switch is disabled.
- Added and verified the 0.7 Stage 4A Auto-Connect preference foundation: one compact Options selector can keep Auto-Connect off or target the last selected location, a current favorite, the fastest location, or another current location sorted by ping. Favorites use yellow/gold status stars while Fastest is later normalized to a neutral symbolic/vector icon; the popup shows roughly 20 rows before scrolling. Stage 4A persists only the selection and deliberately does not connect at application startup yet. Fixed server choices persist only a region ID; unavailable saved targets remain visible but disabled rather than silently falling back to another location.
- Added and verified the 0.7 Stage 3C online public-IP/location provider selector in the fixed-size Options dialog. The maintained choices are FreeIPAPI, GeoJS, and ipwho.is; `country.is` and Cloudflare remain non-selectable research/compatibility adapters. Real Bazzite switching, Cancel behavior, persistence, restart behavior, and immediate refresh all passed. A later Nigeria virtual-location test returned NG only with GeoJS while FreeIPAPI and ipwho.is returned ES, so GeoJS is the 0.7 default and is labeled accordingly in the selector. A local IPinfo Lite database was evaluated and deliberately rejected as excessive for this small display feature because it would add a large redistributable database plus ongoing freshness/update machinery.
- Added and verified the 0.7 Stage 3D server-marker/tray polish: compact server-picking surfaces use neutral `●` for virtual locations and `▶` for streaming-optimized locations; Stage 6A/6B keeps the non-obvious virtual-location explanation in one short sentence while retaining a one-line legend for the Streaming marker. The main selector and tray quick menus share the compact labels, normal favorite add/remove hints are omitted from marker QuickInfo, and the redundant static status dot was removed from the disabled tray status row.
- Added the 0.7 public-network provider core as groundwork for the IP/geolocation option: Stage 3B initially retained `country.is` as its compatibility default, while validated adapters for Cloudflare trace, ipwho.is, FreeIPAPI, and GeoJS plus an IP-only Amazon check endpoint can be exercised independently. Real PIA virtual-location comparison established FreeIPAPI, GeoJS, and ipwho.is as the maintained online candidates; `country.is` and Cloudflare are not planned as selectable country providers.
- Added the 0.7 Options-window foundation: language, appearance/theme, quit behavior, and system-tray visibility are edited in one fixed-size dialog and saved only after explicit confirmation. The selectors now share one consistent label/field grid across sections. The former top-level Options menu is renamed to Tools / Extras; Session Kill Switch, credential re-entry, and Live Log remain direct quick actions instead of being buried in the dialog.
- Added the internal persistent server-favorites core for 0.7 development: up to 10 user-owned PIA region favorites can be stored by region ID with last-known display metadata. Missing regions are retained instead of silently deleted, while stale endpoint and ping data are never persisted as favorite connection data.
- Added the 0.7 main-window favorites UI: server rows expose a separately clickable star, favorites are grouped above the fastest/normal rows, and the popup always opens scrolled to the top so that favorites, Fastest, then the normal ping-sorted regions are visible in that order. Catalog-missing favorites remain visible as disabled rows whose star can still be removed. Active favorite stars use a yellow/gold accent icon. Stage 6A makes Fastest neutral and stabilizes inactive stars to one theme-derived gray across selection states. Catalog-missing non-favorites are not retained.
- Added the 0.7 tray favorites UI: when at least one favorite is saved, the tray root gains a separate `Favorites` submenu directly beside `Connect to…` / `Switch server…`. Available favorites reuse the normal `connect_region()` path, catalog-missing favorites remain visible but disabled, and the tray rebuilds immediately when a favorite changes in the main window. Stage 4C later moved the visual favorite marker to the top-level submenu icon and removed redundant per-row stars.

### Fixed

- Source/development XDG autostart now preserves the active `.venv/bin/python` launcher instead of dereferencing it to the system Python, preventing login autostart from losing venv dependencies such as PySide6. AppImage autostart is unchanged.
- Auto-Connect special-mode icons are rendered from the active PIA Bazzite palette, preventing white symbolic pixels from becoming unreadable when the app uses Light mode with a dark Plasma icon theme. Gold remains reserved for actual favorites.
- Starting PIA Bazzite with the Session Kill Switch merely remembered/armed no longer triggers an unnecessary administrator authorization when the user quits without ever starting a VPN connection. Real or ambiguous surviving Kill Switch state still requires the existing privileged recheck before exit.

## [0.6.0] - 2026-08-08

### Added

- Optional fail-closed Session Kill Switch using a restricted root-owned helper.
- Firewall-first protected connect and VPN-first verified disconnect ordering.
- Protected automatic reconnect and server switching without direct-path fallback.
- Crash-recovery journal and verified automatic takeover after an application crash.
- Adversarial recovery refusal and an integrated VPN-first Reset Kill Switch Protection recovery path.
- Independent IPv4, IPv6, DNS/TCP, and DNS/UDP leak-sentinel host tests.
- Separate verified IPv6-only nftables guard for normal VPN connections without the Session Kill Switch.
- User-facing documentation of why native IPv6 is blocked instead of tunneled with the currently provisioned PIA WireGuard parameters.

### Changed

- Protection status is reconciled automatically on startup when persisted recovery hints indicate that a production Kill Switch firewall may remain active.
- AppImage packaging carries the exact versioned helper payload for authenticated installation and normal-VPN IPv6 protection.
- Release metadata and automation target version 0.6.0.

## [0.5.0] - 2026-08-03

### Added

- First public GitHub release.
- Reproducible x86_64 AppImage build and automated GitHub release workflow.
- Final green and red PIA shield icons.
- `--version` command-line output for packaging smoke tests.
- MIT project license, security policy, contribution guide, and issue forms.

### Changed

- Added Ubuntu's `libpython3.10` runtime package to the AppImage builders so PyInstaller can locate `libpython3.10.so.1.0`.
- Fixed the Ubuntu 22.04 AppImage builder by installing the required `binutils` package.
- AppImage build retries now reuse the existing Python build environment.
- The permanent application icon is the green PIA shield.
- The tray icon is green while connected and red while disconnected.
- A normal tray click opens the main window.
- The native right-click tray menu remains managed by Plasma/Qt.
- All repository and release documentation is English.
- Runtime dependencies are pinned for reproducible builds.

### Retained

- Native NetworkManager WireGuard connections.
- Location search, latency measurements, fastest-location selection, and
  up to 20 quick tray locations.
- Firewall-backed IPv6 protection while connected.
- Secure Secret Service credential storage.
- English and German user interfaces.
- Live log, theme selection, system checks, and detailed connection status.
- Polished server markers: virtual and streaming locations now use compact markers in both the main selector and tray quick menus; marker tooltips were simplified.
- Finalized the compact virtual-location marker as `●` and removed the redundant status-dot icon from the disabled tray status row.
- Polished the new auto-connect selector with gold favorite status stars, neutral special-mode icons, a scrollable ~20-row popup, and clearer two-paragraph QuickInfo.
