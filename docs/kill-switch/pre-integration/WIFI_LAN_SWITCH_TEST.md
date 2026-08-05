# PIA Bazzite guarded Wi-Fi/LAN switch test

This test switches the physical path beneath one WireGuard connection:

1. establish a clean Wi-Fi baseline;
2. activate Ethernet under the independent nftables kill switch;
3. disconnect Wi-Fi and verify WireGuard over Ethernet;
4. force IPv4, IPv6, and real DNS-response probes over Ethernet;
5. restore the original Wi-Fi;
6. disconnect Ethernet and verify WireGuard over Wi-Fi again;
7. repeat the physical leak probes over Wi-Fi.

DNS is considered leaked only when a valid DNS response with the
matching transaction ID is received. A successful UDP `send()` alone
is not treated as delivery.

Start with:

- the temporary LAN cable physically attached;
- PIA Bazzite connected through Wi-Fi;
- no network-sensitive work running.

Run:

```bash
./tools/kill-switch-wifi-lan-switch-test.sh
```

Confirm with `LANBOSS`.

The test intentionally ends with Wi-Fi and PIA connected and Ethernet
disconnected, so the temporary cable can be unplugged immediately.

Report:

`pia-kill-switch-wifi-lan-switch-test.txt`
