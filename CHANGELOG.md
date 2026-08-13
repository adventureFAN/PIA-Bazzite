# Changelog

All notable changes to PIA Bazzite are documented in this file.

## [Unreleased]

### Added

- Added and verified the 0.7 Stage 4C login-autostart/tray polish: Options can create/remove PIA Bazzite's own user XDG autostart entry without administrator privileges. AppImage autostart uses the original `APPIMAGE` path instead of the temporary mount, source runs use the active Python interpreter plus `main.py`, and the generated entry launches with an internal `--autostart` flag. Login autostart stays hidden when the tray is actually enabled and falls back to the main window if the tray is disabled/unavailable; both paths passed real Bazzite login testing, and a duplicate autostart invocation does not raise an already-running instance. The tray root now uses desktop-theme icons (with neutral vector fallbacks) for connect/disconnect, server selection, Favorites, Show, and Quit; the disabled status row remains icon-free and favorite child rows no longer repeat gold stars. Real Bazzite testing also verified a dry `--autostart` launch and a full reboot/login XDG-autostart path with Auto-Connect. The Auto-Connect selector popup always opens scrolled to its first row; its special modes are grouped first as neutral-icon `Off`, neutral-icon `Last selected location`, then the gold Fastest action, followed by gold-starred favorites without a redundant Favorites heading and finally the normal ping-sorted server list. Final real-Bazzite visual verification passed for this selector presentation, so Stage 4C is frozen.
- Added the 0.7 Stage 4B Auto-Connect startup execution candidate: after first-run credentials, the initial fresh server/ping refresh, and both Kill-Switch/IPv6-guard startup reconciliation gates have safely settled, the stored Auto-Connect preference resolves to the exact last/fixed region or the current fastest reachable region and reuses the existing `connect_region()` path. Existing VPN/recovery states take priority, missing fixed targets never fall back silently, failed initial region refresh does not trigger a delayed connection, and each app start can launch Auto-Connect at most once. Real Bazzite verification is still required before Stage 4B is frozen.
- Added and verified the 0.7 Stage 4A Auto-Connect preference foundation: one compact Options selector can keep Auto-Connect off or target the last selected location, a current favorite, the fastest location, or another current location sorted by ping. Favorites and Fastest use the same yellow/gold star and vector-lightning icons as the main server chooser; the popup shows roughly 20 rows before scrolling. Stage 4A persists only the selection and deliberately does not connect at application startup yet. Fixed server choices persist only a region ID; unavailable saved targets remain visible but disabled rather than silently falling back to another location.
- Added and verified the 0.7 Stage 3C online public-IP/location provider selector in the fixed-size Options dialog. The maintained choices are FreeIPAPI, GeoJS, and ipwho.is; `country.is` and Cloudflare remain non-selectable research/compatibility adapters. Real Bazzite switching, Cancel behavior, persistence, restart behavior, and immediate refresh all passed. A later Nigeria virtual-location test returned NG only with GeoJS while FreeIPAPI and ipwho.is returned ES, so GeoJS is the 0.7 default and is labeled accordingly in the selector. A local IPinfo Lite database was evaluated and deliberately rejected as excessive for this small display feature because it would add a large redistributable database plus ongoing freshness/update machinery.
- Added and verified the 0.7 Stage 3D server-marker/tray polish: compact server-picking surfaces use neutral `●` for virtual locations and `▶` for streaming-optimized locations, with marker-specific DE/EN QuickInfo. The main selector and tray quick menus share the compact labels, normal favorite add/remove hints are omitted from marker QuickInfo, and the redundant static status dot was removed from the disabled tray status row.
- Added the 0.7 public-network provider core as groundwork for the IP/geolocation option: Stage 3B initially retained `country.is` as its compatibility default, while validated adapters for Cloudflare trace, ipwho.is, FreeIPAPI, and GeoJS plus an IP-only Amazon check endpoint can be exercised independently. Real PIA virtual-location comparison established FreeIPAPI, GeoJS, and ipwho.is as the maintained online candidates; `country.is` and Cloudflare are not planned as selectable country providers.
- Added the 0.7 Options-window foundation: language, appearance/theme, quit behavior, and system-tray visibility are edited in one fixed-size dialog and saved only after explicit confirmation. The selectors now share one consistent label/field grid across sections. The former top-level Options menu is renamed to Tools / Funktionen; Session Kill Switch, credential re-entry, and Live Log remain direct quick actions instead of being buried in the dialog.
- Added the internal persistent server-favorites core for 0.7 development: up to 10 user-owned PIA region favorites can be stored by region ID with last-known display metadata. Missing regions are retained instead of silently deleted, while stale endpoint and ping data are never persisted as favorite connection data.
- Added the 0.7 main-window favorites UI: server rows expose a separately clickable star, favorites are grouped above the fastest/normal rows, and the popup always opens scrolled to the top so that favorites, Fastest, then the normal ping-sorted regions are visible in that order. Catalog-missing favorites remain visible as disabled rows whose star can still be removed. Active favorite stars and the Fastest marker use a yellow/gold accent icon while inactive stars follow the current theme text color. Catalog-missing non-favorites are not retained.
- Added the 0.7 tray favorites UI: when at least one favorite is saved, the tray root gains a separate `Favorites` submenu directly beside `Connect to…` / `Switch server…`. Available favorites reuse the normal `connect_region()` path, catalog-missing favorites remain visible but disabled, and the tray rebuilds immediately when a favorite changes in the main window. Stage 4C later moved the visual favorite marker to the top-level submenu icon and removed redundant per-row stars.

### Fixed

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
- Polished the new auto-connect selector with gold favorite/fastest markers, a scrollable ~20-row popup, and clearer two-paragraph QuickInfo.
