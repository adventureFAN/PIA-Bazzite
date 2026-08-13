# PIA Bazzite 0.7.0

PIA Bazzite 0.7.0 focuses on everyday usability: persistent server favorites,
Auto-Connect, login autostart, better location discovery, configurable public
IP/location providers, physical-network awareness, and a KDE-oriented UI polish
pass. The verified Session Kill Switch and normal-mode IPv6 leak protection from
0.6 remain intact.

## Server favorites and location discovery

- Save up to 10 favorite PIA regions. Favorites stay visible even if a region
  temporarily disappears from the current PIA catalog; stale endpoints are never
  used for a connection.
- Favorites are available from both the main selector and a dedicated tray submenu.
- Search understands location names plus normal, virtual, and streaming-optimized
  location types.
- An integrated filter can show all, normal, virtual, or streaming-optimized
  locations and can be combined with text search.
- Compact markers identify virtual (`●`) and streaming-optimized (`▶`) locations;
  the virtual-location tooltip explains that the physical server may be in another
  country.

## Auto-Connect and login autostart

- Auto-Connect can stay off or target the last selected location, the current
  fastest reachable location, a favorite, or another fixed PIA region.
- Fixed targets never silently fall back to a different country if their region is
  unavailable.
- Existing VPN/recovery state takes priority, so app restart does not trigger a
  second connection when an existing VPN can be safely adopted.
- PIA Bazzite can start automatically after desktop login. With the system tray
  enabled it starts quietly in the tray; with the tray disabled the main window is
  shown so the app never becomes invisible.
- A fresh Auto-Connect may still require administrator authorization. With the
  Session Kill Switch enabled this authorizes the protected session; with it
  disabled the separate IPv6-only firewall guard is still privileged leak
  prevention.

## Public IP and virtual-location providers

- The public IP/country display can use **GeoJS** (default), **FreeIPAPI**, or
  **ipwho.is**. The provider can be changed without restarting the VPN.
- The public IP/location display can be disabled completely, which also suppresses
  those external provider lookups.
- GeoJS became the default after real PIA virtual-location comparisons, including a
  Nigeria virtual-location case where it matched the intended country while the
  other maintained providers did not.

## Physical-network awareness

PIA Bazzite now watches NetworkManager's physical underlay separately from the
administratively active WireGuard profile. If Wi-Fi or Ethernet disappears while
the VPN profile remains active, the UI no longer misleadingly stays in a normal
connected state:

- Session Kill Switch mode presents protected network loss as Orange and keeps the
  verified firewall authoritative.
- Normal VPN mode presents the unavailable physical path as neutral Grey instead of
  stale Blue.
- When the physical network returns, PIA Bazzite rechecks the VPN/protection state
  and refreshes public network information.

This detection does not add a second reconnect algorithm; existing audited
NetworkManager/Kill-Switch recovery remains responsible for recovery.

## Options, tray, and KDE-oriented UI polish

- The fixed-size Options window now uses **General**, **Connection**, and
  **Network & Privacy** tabs.
- New options control security/error notifications, active-VPN server-switch
  confirmation, and whether public IP/location information is shown.
- PIA Bazzite deliberately avoids duplicating ordinary NetworkManager connect/
  disconnect notifications and reserves its own notifications for relevant
  background protection or Auto-Connect failures.
- Closing the main window to the tray no longer shows the repetitive
  “minimized to tray” notification.
- Tray actions use KDE-style monochrome icons; gold remains reserved for actual
  favorite status.
- The compact main window is narrower, while the Live Log expands to its larger
  diagnostic layout only when needed.
- Real Bazzite release testing passed DE/EN, Light/Dark, and Plasma 125%/150% UI
  scaling checks.

## Session Kill Switch and IPv6 protection

The optional Session Kill Switch remains **session-scoped**, not a persistent
boot-time firewall. It is designed to remain fail-closed across unexpected VPN
loss, protected reconnect/server switching, and GUI crash/restart while the current
operating-system session remains alive. A full reboot, kernel crash, or power loss
clears this runtime `nftables` state.

Normal VPN mode still arms a separate IPv6-only `nftables` guard before the VPN
starts. The WireGuard parameters currently provisioned to this client provide an
IPv4 tunnel/default route but no tunneled IPv6 `AllowedIPs` route, so PIA Bazzite
blocks native IPv6 while connected instead of allowing it to bypass the VPN.

**Reset Kill Switch Protection** remains VPN-first and fail-closed: the VPN must be
verified down before PIA Bazzite removes only its own fixed Kill Switch table. After a successful reset, normal networking is outside VPN protection and the real public IP address may be visible.

## Installation

Download `PIA-Bazzite-0.7.0-x86_64.AppImage` from the GitHub release and
integrate it with Gear Lever, or mark it executable and launch it directly. The
AppImage bundles Python, Qt/PySide6, and the Python dependencies while continuing
to use the host NetworkManager, WireGuard, D-Bus, and Secret Service integration.

## Known limitations

PIA Bazzite 0.7.0 still does not provide trusted-network rules, port forwarding,
split tunneling, or boot-persistent/early-boot Kill Switch protection. Support is
focused on Bazzite.

## Project credits

Project direction, feature design, testing, and release decisions: **adventureFAN**  
Most implementation, debugging, and technical documentation: developed collaboratively with **ChatGPT**

This project is unofficial and is not affiliated with Private Internet Access
or endorsed by the Bazzite project.
