# Kill Switch Runtime Integration — Stage 4C

Stage 4C connects the real main-window status widget and tray presentation to a read-only runtime controller.

## Scope

This stage does **not** install the helper, open Polkit, change NetworkManager, or modify nftables. It only combines:

- whether the optional kill switch is enabled in settings;
- whether the VPN is currently connected;
- a verified `KillSwitchStatus` returned by an already-authorized `KillSwitchSessionClient`.

The GUI and tray now use the same derived state. Protection is never inferred from the VPN connection alone.

## Optional states

The optional feature requires two additional honest states:

1. **Ready** — VPN disconnected, kill switch disabled, normal connection active.
2. **Kill switch ready** — VPN intentionally disconnected, feature enabled for the next connection, no firewall lock active yet.
3. **VPN connected** — VPN connected, kill switch disabled. This is shown in blue and is not described as full kill-switch protection.
4. **Protected** — VPN connected and the helper verified the firewall table.
5. **Safely blocked** — VPN unavailable while the verified firewall table blocks normal internet traffic.
6. **Protection error** — the feature is enabled but its protection cannot be verified, or a table exists while the feature is disabled.

## Conservative behavior

- When the feature is disabled, the runtime controller never calls the privileged status reader.
- When the feature is enabled but no authorized session is available, the UI shows a protection error instead of guessing.
- A VPN-only connection receives a separate blue state and never the green protected state.
- The main window, tray icon, tray menu, tooltip, and Live Log share one derived `KillSwitchViewState`.

## Testing

The Stage-4C self-test uses the real `KillSwitchSessionClient` parser and session protocol with a deterministic in-process transport. This proves that real client status objects reach the runtime controller without using pkexec or the firewall.

The visual preview is still deliberately simulated and network-free. It exposes all six states through the Preview menu and keyboard shortcuts Ctrl+1 through Ctrl+6.
