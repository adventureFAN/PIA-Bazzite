# PIA Bazzite guarded NetworkManager restart test

This test restarts the complete NetworkManager service while an
independent nftables kill-switch table is active.

Sequence:

1. detect the active Wi-Fi, PIA profile, endpoint, and WireGuard mark;
2. install an independent kill-switch table;
3. arm a root-owned safety reset;
4. withhold the PIA endpoint and deactivate WireGuard;
5. restart NetworkManager completely;
6. verify that the nftables table and safety timer survived;
7. restore only the original Wi-Fi;
8. require physical IPv4, IPv6, DNS, and ordinary traffic to remain
   blocked;
9. restore the endpoint and obtain a fresh WireGuard handshake;
10. remove the test table and timer.

Start with PIA Bazzite connected over the normal Wi-Fi:

```bash
./tools/kill-switch-networkmanager-restart-test.sh
```

Confirm with `NETWORK`.

Do not interact with Plasma networking or PIA Bazzite while the test
runs.

Report:

`pia-kill-switch-networkmanager-restart-test.txt`
