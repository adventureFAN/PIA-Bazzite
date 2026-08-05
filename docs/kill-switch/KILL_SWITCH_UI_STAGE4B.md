# Stage 4B — Main-window status presentation

Stage 4B moves the kill-switch presentation from the separate state gallery into
the real `MainWindow` layout while keeping all security and network behavior
simulated.

## User-facing states

The main window now has three information levels:

1. a color and unambiguous state title;
2. one short visible consequence;
3. a complete explanation as a tooltip on the whole status panel.

| Color | State | Visible consequence |
| --- | --- | --- |
| Gray | Ready | VPN disconnected; normal connection active |
| Green | Protected | VPN connected; kill switch verified |
| Orange | Safely blocked | VPN disconnected; no normal internet access |
| Red | Protection error | Protection not guaranteed |

The detailed tooltip explicitly states whether the real public IP is being used,
whether traffic is restricted to the VPN tunnel, or whether the VPN was not
started / was disconnected because protection could not be verified.

## Live Log scope

The normal Live Log records meaningful events and their consequences:
activation, verification, loss of the VPN, continued blocking, and protection
errors. Packet and byte counters are deliberately excluded from the normal log
because they are noisy and easily misinterpreted. Such counters may later be
added to a diagnostic report or optional details view.

## Safe preview mode

`tools/pia-bazzite-stage4b-main-window-preview.py` constructs the real
`MainWindow` with `stage4_preview=True`. In that mode the application:

- does not run first-start credentials;
- does not fetch regions or public network information;
- does not call NetworkManager;
- does not start Polkit, the helper, or nftables;
- does not show a system-tray icon;
- exposes the four simulated states through the **Preview** menu and
  `Ctrl+1` through `Ctrl+4`.

The production constructor keeps `stage4_preview=False` by default. The compact
status widget remains hidden in normal operation until Stage 4C connects it to
real verified helper observations.
