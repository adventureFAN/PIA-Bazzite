# PIA Bazzite guarded failed-reconnect test

This test intentionally withholds the current WireGuard endpoint from
the kill-switch allow set.

It verifies that:

- NetworkManager cannot produce a fresh WireGuard handshake while the
  endpoint is blocked;
- IPv4, IPv6, and direct DNS traffic cannot fall back;
- the nftables block counter increases during the failed attempt;
- restoring the endpoint allows WireGuard to recover without disabling
  the kill switch;
- the temporary table and safety timer are removed afterward.

Start while PIA Bazzite is connected:

```bash
./tools/kill-switch-failed-reconnect-test.sh
```

Confirm with `FAILSAFE`.

Report:

`pia-kill-switch-failed-reconnect-test.txt`
