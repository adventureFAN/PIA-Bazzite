# Changelog

All notable changes to PIA Bazzite are documented in this file.

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
  ten quick tray locations.
- Temporary IPv6 protection while connected.
- Secure Secret Service credential storage.
- English and German user interfaces.
- Live log, theme selection, system checks, and detailed connection status.
