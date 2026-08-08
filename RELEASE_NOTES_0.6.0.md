# PIA Bazzite 0.6.0

PIA Bazzite 0.6.0 adds the optional **Session Kill Switch** to the unofficial
Private Internet Access desktop client for Bazzite.

## Session Kill Switch

- Activates the firewall before a protected VPN connection is started.
- Blocks ordinary IPv4, IPv6, and direct DNS traffic outside the protected path.
- Keeps the firewall active across unexpected tunnel loss and performs a
  fail-closed protected reconnect.
- Switches PIA locations without opening the ordinary network path between the
  old and new tunnels.
- Keeps protection active if the PIA Bazzite GUI is killed and can verify and
  adopt the existing protected state after the app is restarted.
- Refuses corrupted recovery data and unowned firewall state rather than making
  unsafe assumptions.
- Provides an integrated **Help → Reset Kill Switch Protection…** path when a
  known Kill Switch firewall remains in a safely blocked or protection-error
  state. It stops and verifies the VPN first, keeps the firewall active during
  that check, removes only PIA Bazzite's fixed Kill Switch firewall through the
  installed helper, verifies the table is absent, and only then cleans the
  crash-recovery record. After a successful reset, normal networking is no
  longer VPN-protected and the real public IP address may be visible.

The Kill Switch is optional. It is a **session** Kill Switch, not a persistent
boot-time firewall; a full system reboot is outside its protection lifetime.

Bazzite/KDE may show **Limited connectivity** while the Session Kill Switch is
active because NetworkManager's own connectivity probe is intentionally not
allowed to bypass the VPN through the physical interface. After a deliberate
disconnect, that desktop indicator can remain limited briefly until
NetworkManager performs its next connectivity check.

## IPv6 protection in normal VPN mode

PIA Bazzite now prevents native IPv6 from bypassing the PIA WireGuard tunnel
even when the optional Session Kill Switch is disabled. A separate IPv6-only
`nftables` guard is armed and verified before the normal VPN starts and is
released only after the VPN is verified down. It leaves ordinary IPv4
unblocked, so it is deliberately not a full Kill Switch.

### Why IPv6 is blocked instead of tunneled

The WireGuard parameters currently provisioned to PIA Bazzite by PIA provide an
IPv4 tunnel address and an IPv4 default route; the PIA WireGuard peer used by
this client does not provide an IPv6 `AllowedIPs` route for tunneled IPv6. PIA
Bazzite therefore does not invent an IPv6 tunnel path that PIA has not
provisioned. Instead, native IPv6 is deliberately blocked for the lifetime of
the VPN connection so it cannot bypass the VPN over the physical network.

This is intentional leak prevention, not a claim that Bazzite or the local
network lacks IPv6. After an intentional VPN disconnect, the IPv6-only guard is
removed and the system's normal IPv6 connectivity is restored. With the Session
Kill Switch enabled, the full fail-closed firewall remains authoritative for
both IPv4 and IPv6 instead of the smaller normal-mode guard.

Real dual-stack Bazzite validation confirmed both modes independently: normal
VPN traffic selected the PIA WireGuard interface for IPv4 while native IPv6 was
blocked by the dedicated guard, and the Session Kill Switch independently
blocked IPv6 with its full firewall. In both cases, an intentional disconnect
removed the corresponding protection and restored normal IPv4 and IPv6.

## Packaging

The 0.6.0 AppImage carries the exact helper payload required by both the normal
IPv6 guard and the optional Session Kill Switch. The helper is installed to a
fixed root-owned system path only after explicit administrator authorization and
is verified before privileged operations are accepted.

## Existing features

PIA Bazzite continues to provide native NetworkManager WireGuard connections,
PIA location selection and latency measurement, tray controls, public-IP status,
secure Secret Service credential storage, English/German interfaces, live logs,
and System/Light/Dark appearance modes.

## Installation

Download `PIA-Bazzite-0.6.0-x86_64.AppImage` and integrate it with Gear Lever or
mark it executable and launch it. On first protected VPN use, PIA Bazzite asks
before installing the required system helper and uses the normal desktop
administrator authorization flow. A later AppImage with a different helper
requires an explicit helper update instead of silently reusing it.

## Project credits

Project direction, feature design, testing, and release decisions: **adventureFAN**  
Most implementation, debugging, and technical documentation: developed collaboratively with **ChatGPT**

This project is unofficial and is not affiliated with Private Internet Access
or endorsed by the Bazzite project.
