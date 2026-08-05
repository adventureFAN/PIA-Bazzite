# PIA Bazzite guarded firewalld-reload test

This test checks whether PIA Bazzite's separate nftables table survives
a normal firewalld reload.

It verifies that:

- firewalld remains active;
- the independent PIA Bazzite test table survives `firewall-cmd --reload`;
- VPN traffic still works afterward;
- IPv4, IPv6, and direct DNS cannot fall back after the tunnel is removed;
- the existing WireGuard profile can reconnect under protection;
- all temporary rules and the safety timer are removed afterward.

Before starting:

1. Connect PIA Bazzite normally.
2. Pause network-sensitive work.
3. Optionally prepare the emergency reset in another terminal:

   ```bash
   cd /home/alex/PIA-Bazzite
   ./tools/kill-switch-emergency-reset.sh
   ```

Start:

```bash
./tools/kill-switch-firewalld-reload-test.sh
```

Confirm with `RELOAD`.

The report is saved as:

`pia-kill-switch-firewalld-reload-test.txt`
