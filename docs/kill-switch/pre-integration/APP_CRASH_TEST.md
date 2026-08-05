# PIA Bazzite guarded application-crash test

This test intentionally terminates the PIA Bazzite GUI with `SIGKILL`.
The application receives no opportunity to run cleanup code.

It verifies that:

- the independent nftables table survives the application crash;
- NetworkManager initially keeps the WireGuard tunnel alive;
- the VPN still carries traffic without the GUI;
- removing the tunnel afterward does not expose IPv4, IPv6, or DNS;
- the block counter increases while the application is absent;
- NetworkManager can reconnect WireGuard under protection;
- the temporary table and safety timer are removed afterward.

Before starting:

1. Launch PIA Bazzite from Favorites.
2. Connect to any PIA location.
3. Pause network-sensitive work.
4. Optionally prepare the emergency reset in a second terminal:

   ```bash
   cd /home/alex/PIA-Bazzite
   ./tools/kill-switch-emergency-reset.sh
   ```

Start:

```bash
./tools/kill-switch-app-crash-test.sh
```

Confirm first with `CRASH`, then with `KILL`.

The GUI will remain closed after a successful test. Launch it again from
Favorites.

The report is saved as:

`pia-kill-switch-app-crash-test.txt`
