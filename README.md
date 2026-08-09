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
- Quick access to up to 20 low-latency locations from the system tray.
- Native NetworkManager and Plasma notification integration.
- Public IP and detected country display.
- Optional fail-closed Session Kill Switch for IPv4, IPv6, and direct DNS paths.
- Protected reconnect and server switching while the Kill Switch remains active.
- Crash-safe recovery and verified automatic takeover after an application restart.
- Integrated VPN-first **Reset Kill Switch Protection** recovery for deliberate
  release from a stuck blocked/error state.
- Verified IPv6-only firewall protection while connected when the Session Kill Switch is disabled.
- PIA DNS configuration in the WireGuard profile.
- Secure credential storage through the Linux Secret Service keyring.
- English and German user interfaces.
- System, Light, and Dark appearance modes.
- Optional live log with secret redaction and IP masking.
- Single-instance behavior and XDG-compliant storage locations.

### Public-IP lookup privacy

The Public IP / country display uses `https://api.country.is/`. PIA Bazzite does
not automatically query that service while the VPN is verified disconnected.
While disconnected, the lookup is performed only when you explicitly use the
public-IP refresh control. Automatic refreshes are limited to a verified VPN
connection.

> [!IMPORTANT]
> **Kill Switch scope:** PIA Bazzite's optional Kill Switch protects the current
> running session. If the VPN tunnel or PIA Bazzite GUI fails while the system
> remains running, the firewall stays fail-closed and can be verified/adopted by
> the app after restart. A full system reboot, kernel crash, or power loss clears
> this runtime `nftables` state. PIA Bazzite is not an early-boot firewall: after
> boot, its Kill Switch protection is not active until PIA Bazzite runs and the
> Kill Switch is activated again.

## Important limitations

The optional Kill Switch is intentionally a **session Kill Switch**, not
boot-persistent protection. The security boundary is described explicitly above.

While the Session Kill Switch is active, Bazzite/KDE may temporarily report the
underlying network as **Limited connectivity**. This can happen because
NetworkManager's own connectivity probe is not allowed to bypass the VPN through
the physical interface. It does not by itself mean that the PIA tunnel is down.
After an intentional disconnect and firewall release, the indicator may remain
limited briefly until NetworkManager performs its next connectivity check.

PIA Bazzite also does not provide:

- split tunneling;
- port forwarding;
- automatic connection at login;
- support guarantees outside Bazzite.

## Recommended installation: AppImage

1. Download `PIA-Bazzite-0.6.0-x86_64.AppImage` from the GitHub release.
2. Integrate it with **Gear Lever**, or mark it executable and launch it.
3. Enter your PIA username and password on first start.
4. Choose a location and connect.

The AppImage includes Python, Qt/PySide6, and the Python dependencies. It
still uses Bazzite's own NetworkManager and WireGuard support. Normal VPN
connections use a narrow IPv6-only `nftables` guard so native IPv6 cannot bypass
the PIA tunnel; the optional Session Kill Switch uses a separate, stronger
fail-closed firewall. Both are managed by the same restricted root-owned system
component after administrator authorization.

### Why PIA Bazzite blocks IPv6 while connected

The WireGuard parameters currently provisioned to PIA Bazzite by PIA provide an
IPv4 tunnel address and IPv4 default route, but no IPv6 `AllowedIPs` route for
tunneled IPv6. PIA Bazzite therefore blocks native IPv6 while the VPN is active
rather than allowing IPv6 to leave through the physical network outside the VPN.
This does not disable IPv6 permanently: after an intentional VPN disconnect,
the guard is removed and the system's normal IPv6 connectivity is restored.

### Reset Kill Switch Protection

When a safely blocked or protection-error state has a known PIA Bazzite Kill
Switch firewall, **Help → Reset Kill Switch Protection…** becomes available as
a deliberate recovery action. The app first stops the PIA WireGuard profile and
independently verifies that the VPN is down. The Kill Switch firewall remains in
place during that verification. Only then may the fixed installed helper remove
PIA Bazzite's own `pia_bazzite_killswitch` table. The helper verifies that the
table is absent before the crash-recovery record is cleaned up. Other firewall
tables are not modified, and the Kill Switch preference remains enabled for the
next VPN connection.

After a successful reset, normal networking is restored **without VPN
protection**, so the user's real public IP address may be visible. If VPN-down
or firewall absence cannot be verified, the reset fails closed and does not
claim that normal networking has been restored.

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
| Refresh server list | `Ctrl+R` |
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
AppImage automatically when a version tag such as `v0.6.0` is pushed.

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

## Project credits

Project direction, feature design, testing, and release decisions: **adventureFAN**  
Most implementation, debugging, and technical documentation: developed collaboratively with **ChatGPT**

## License

PIA Bazzite is released under the MIT License. See `LICENSE`.
Third-party notices are listed in `THIRD_PARTY_NOTICES.md`.
