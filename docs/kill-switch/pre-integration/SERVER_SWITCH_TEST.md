# PIA Bazzite guarded server-switch test v2

This revision corrects the final endpoint-retirement check.

In the first test, the probe to the retired server followed the active
VPN default route and was correctly accepted as VPN traffic. It therefore
did not test the physical Wi-Fi escape path.

Version 2:

- binds the endpoint probes to the physical interface;
- applies the replacement WireGuard fwmark;
- checks endpoint-set membership directly;
- uses nftables counters as the authoritative result;
- treats a changed fwmark as valid when NetworkManager replaces the
  WireGuard profile;
- instructs the tester to switch through the current tray menu.

Start while PIA Bazzite is connected:

```bash
./tools/kill-switch-server-switch-test.sh
```

When instructed, use the PIA Bazzite system-tray menu to select a
clearly different country.

A root-owned timer removes the temporary test table after 240 seconds.
