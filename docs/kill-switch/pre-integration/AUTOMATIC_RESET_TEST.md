# PIA Bazzite automatic safety-reset test

This test intentionally blocks the current PIA endpoint and disconnects
WireGuard. After 35 seconds, an independent root-owned transient systemd unit
must remove the temporary nftables table and reconnect the saved PIA profile.

Run while PIA Bazzite is connected:

```bash
./tools/kill-switch-automatic-reset-test.sh
```

Confirm with `RESET`. Do not change Wi-Fi, Ethernet, or PIA during the test.

Report: `pia-kill-switch-automatic-reset-test.txt`
