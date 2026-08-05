# PIA Bazzite guarded host-test preflight v2

This revision fixes WireGuard status detection on systems where `wg show`
requires administrator privileges.

The script still performs read-only checks only. It does not:

- create or remove firewall rules;
- disconnect or reconnect PIA;
- change NetworkManager;
- change systemd services.

Run it while PIA Bazzite is connected:

```bash
./tools/kill-switch-host-preflight.sh
```

The report is saved as `pia-kill-switch-host-preflight-v2.txt`.
