# Security policy

## Supported version

Only the latest release is supported.

## Reporting a vulnerability

Do not publish credentials, PIA tokens, WireGuard private keys, crash-recovery
records, or other sensitive material in a public issue. Open a minimal issue
without secrets and ask for a private contact channel.

## Session Kill Switch

PIA Bazzite 0.6.0 includes an optional fail-closed **Session Kill Switch**. It
uses a small root-owned helper, authorized through Polkit, to manage one fixed
nftables boundary. The GUI remains unprivileged.

The Kill Switch is session-scoped: it is designed to survive VPN loss, server
switches, reconnects, and a GUI crash/restart while the current operating-system
session remains alive. It is not a boot-time or pre-login firewall and must not
be described as protection across a reboot.

AppImage releases carry an exact helper manifest and hashes. A helper install or
upgrade is copied from the user-readable AppImage into private staging, anchored
to the verified manifest digest, copied again into a root-owned staging tree,
and revalidated before the fixed system helper is replaced. Packaged installs
must not silently fall back to the developer/source-tree install mode.

## Normal VPN IPv6 containment

PIA's WireGuard path used by PIA Bazzite is IPv4-only. When the optional Session
Kill Switch is disabled, PIA Bazzite therefore arms a separate, narrowly scoped
`pia_bazzite_ipv6_guard` nftables table before starting the normal VPN. That
guard blocks outbound native IPv6 only; it does not block ordinary IPv4 and is
not a Kill Switch. On an intentional disconnect, the VPN is verified down before
the small guard is released. If the app cannot verify the transition, it retains
the guard rather than opening an unverified IPv6 path.

The normal IPv6 guard and the full Session Kill Switch use distinct fixed tables
and helper status types and are not allowed to be armed at the same time. The
full Session Kill Switch remains the authoritative fail-closed mechanism when
that feature is enabled.

## Privacy notes

PIA credentials are stored through the configured system keyring. PIA tokens and
WireGuard private keys must not be written to the live log. The live log also
masks public IP addresses, but users should still inspect logs before sharing
them.

The public-IP/country display uses `https://api.country.is/`. PIA Bazzite does
not automatically contact that service while the VPN is verified disconnected.
A disconnected lookup happens only when the user explicitly requests a public-IP
refresh; automatic refreshes are limited to a verified VPN connection.
