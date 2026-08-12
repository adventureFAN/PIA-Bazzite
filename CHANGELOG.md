# Changelog

All notable changes to PIA Bazzite are documented in this file.

## [Unreleased]

### Added

- Added and verified the 0.7 Stage 3C online public-IP/location provider selector in the fixed-size Options dialog. The maintained choices are FreeIPAPI, GeoJS, and ipwho.is; `country.is` and Cloudflare remain non-selectable research/compatibility adapters. Real Bazzite switching, Cancel behavior, persistence, restart behavior, and immediate refresh all passed. A later Nigeria virtual-location test returned NG only with GeoJS while FreeIPAPI and ipwho.is returned ES, so GeoJS is the 0.7 default and is labeled accordingly in the selector. A local IPinfo Lite database was evaluated and deliberately rejected as excessive for this small display feature because it would add a large redistributable database plus ongoing freshness/update machinery.
- Added the 0.7 public-network provider core as groundwork for the IP/geolocation option: Stage 3B initially retained `country.is` as its compatibility default, while validated adapters for Cloudflare trace, ipwho.is, FreeIPAPI, and GeoJS plus an IP-only Amazon check endpoint can be exercised independently. Real PIA virtual-location comparison established FreeIPAPI, GeoJS, and ipwho.is as the maintained online candidates; `country.is` and Cloudflare are not planned as selectable country providers.
- Added the 0.7 Options-window foundation: language, appearance/theme, quit behavior, and system-tray visibility are edited in one fixed-size dialog and saved only after explicit confirmation. The selectors now share one consistent label/field grid across sections. The former top-level Options menu is renamed to Tools / Funktionen; Session Kill Switch, credential re-entry, and Live Log remain direct quick actions instead of being buried in the dialog.
- Added the internal persistent server-favorites core for 0.7 development: up to 10 user-owned PIA region favorites can be stored by region ID with last-known display metadata. Missing regions are retained instead of silently deleted, while stale endpoint and ping data are never persisted as favorite connection data.
- Added the 0.7 main-window favorites UI: server rows expose a separately clickable star, favorites are grouped above the fastest/normal rows, and the popup always opens scrolled to the top so that favorites, Fastest, then the normal ping-sorted regions are visible in that order. Catalog-missing favorites remain visible as disabled rows whose star can still be removed. Active favorite stars and the Fastest marker use a yellow/gold accent icon while inactive stars follow the current theme text color. Catalog-missing non-favorites are not retained.
- Added the 0.7 tray favorites UI: when at least one favorite is saved, the tray root gains a separate `Favorites` submenu directly beside `Connect to…` / `Switch server…`; the submenu itself has no icon, while individual favorite actions use the yellow/gold star marker. The normal server submenu remains unchanged. Available favorites reuse the normal `connect_region()` path, catalog-missing favorites remain visible but disabled, and the tray rebuilds immediately when a favorite changes in the main window.

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
