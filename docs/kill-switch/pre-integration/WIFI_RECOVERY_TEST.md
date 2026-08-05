# PIA Bazzite guarded Wi-Fi outage and recovery test

This test temporarily disconnects the active Wi-Fi profile while an
independent nftables kill switch remains active.

It verifies that:

- complete Wi-Fi loss also removes the WireGuard tunnel;
- the kill-switch table remains in the kernel;
- DHCP and local IPv6 maintenance traffic can restore Wi-Fi;
- restored Wi-Fi cannot carry ordinary IPv4, IPv6, or direct DNS traffic
  before WireGuard returns;
- the existing PIA endpoint remains reachable;
- WireGuard can complete a fresh handshake afterward;
- firewalld remains active;
- all temporary rules and the recovery timer are removed.

Safety measures:

- a root-owned systemd timer removes the test table after 300 seconds;
- that timer also attempts to restore the original Wi-Fi and VPN profiles;
- the script cleanup performs the same recovery on normal exit;
- an emergency reset helper is included.

Before starting:

1. Connect PIA Bazzite through Wi-Fi.
2. Pause downloads, calls, games, and other network-sensitive work.
3. Optionally prepare this in a second terminal:

   ```bash
   cd /home/alex/PIA-Bazzite
   ./tools/kill-switch-emergency-reset.sh
   ```

Start:

```bash
./tools/kill-switch-wifi-recovery-test.sh
```

Confirm with `WIFI`.

The report is saved as:

`pia-kill-switch-wifi-recovery-test.txt`
