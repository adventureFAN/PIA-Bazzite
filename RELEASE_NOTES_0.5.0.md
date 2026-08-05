# PIA Bazzite 0.5.0

PIA Bazzite 0.5.0 is the first public release of the unofficial
Private Internet Access desktop client built specifically for Bazzite.

## What it does

- Connects to PIA through native NetworkManager WireGuard profiles.
- Loads PIA locations and measures their latency.
- Provides fast connect, disconnect, and location switching from the tray.
- Displays the public IP, detected country, DNS status, IPv6 protection,
  and kill-switch status.
- Stores PIA credentials in the Linux system keyring.
- Supports English and German interfaces and System, Light, and Dark modes.

## Installation

Download `PIA-Bazzite-0.5.0-x86_64.AppImage` and integrate it with
Gear Lever. On first start, enter your PIA username and password.

## Important warning

This release does not include a kill switch. If the VPN disconnects
unexpectedly, traffic may continue through the normal internet connection.

This project is unofficial and is not affiliated with Private Internet
Access or endorsed by the Bazzite project.
