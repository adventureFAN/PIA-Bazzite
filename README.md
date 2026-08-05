# PIA Bazzite

**PIA Bazzite** is an unofficial desktop client for Private Internet Access
on Bazzite. It creates native WireGuard connections through NetworkManager
and does not require PIA's `manual-connections` repository.

> [!WARNING]
> This project is unofficial, not affiliated with Private Internet Access,
> and not endorsed by the Bazzite project. Use it at your own risk.

## Highlights

- Connect, disconnect, and switch PIA locations.
- Measure locations and sort them by latency.
- Choose the fastest location automatically.
- Quick access to ten low-latency locations from the system tray.
- Native NetworkManager and Plasma notification integration.
- Public IP and detected country display.
- Temporary IPv6 blackhole protection while connected.
- PIA DNS configuration in the WireGuard profile.
- Secure credential storage through the Linux Secret Service keyring.
- English and German user interfaces.
- System, Light, and Dark appearance modes.
- Optional live log with secret redaction and IP masking.
- Single-instance behavior and XDG-compliant storage locations.

## Important limitations

PIA Bazzite currently has **no kill switch**. If the VPN tunnel drops
unexpectedly, normal internet traffic may resume outside the VPN.

It also does not provide:

- split tunneling;
- port forwarding;
- automatic connection at login;
- support guarantees outside Bazzite.

## Recommended installation: AppImage

1. Download `PIA-Bazzite-0.5.0-x86_64.AppImage` from the GitHub release.
2. Integrate it with **Gear Lever**, or mark it executable and launch it.
3. Enter your PIA username and password on first start.
4. Choose a location and connect.

The AppImage includes Python, Qt/PySide6, and the Python dependencies. It
still uses Bazzite's own NetworkManager and WireGuard support.

## Run from source

Source execution is intended for development and troubleshooting:

```bash
chmod +x setup.sh run.sh self_test.py
./setup.sh
./self_test.py
./run.sh
```

## Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Exit | `Ctrl+Q` |
| Connect / disconnect | `Ctrl+Shift+V` |
| Reload server list | `Ctrl+R` |
| Refresh pings | `Ctrl+P` |
| Check public IP | `Ctrl+I` |
| System check | `F5` |
| Show or hide live log | `Ctrl+L` |
| About | `F1` |

## Stored data

- Settings: `~/.config/pia-bazzite/settings.ini`
- Cache: `~/.cache/pia-bazzite/`
- Optional saved logs: `~/.local/state/pia-bazzite/` by default
- Password: Linux system keyring only

Passwords, PIA tokens, and WireGuard private keys are never written to the
application log.

## Building the AppImage

The release workflow builds on Ubuntu 22.04 and creates the x86_64
AppImage automatically when a version tag such as `v0.5.0` is pushed.

A local build is also available:

```bash
./packaging/build-appimage.sh
```

On Bazzite, the recommended reproducible local build uses Podman and Ubuntu
22.04:

```bash
./packaging/build-appimage-podman.sh
```

The finished AppImage and its SHA-256 checksum are written to `dist/`.
The build requires internet access and an x86_64 build machine.

## License

PIA Bazzite is released under the MIT License. See `LICENSE`.
Third-party notices are listed in `THIRD_PARTY_NOTICES.md`.
