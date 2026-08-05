# PIA Bazzite guarded full firewalld restart test

This test performs `systemctl restart firewalld`, not merely
`firewall-cmd --reload`.

It verifies that:

- the firewalld main process is actually replaced;
- the independent PIA Bazzite nftables table survives;
- the root-owned safety timer survives;
- the withheld PIA endpoint does not reappear;
- physical IPv4, IPv6, valid DNS responses, and ordinary public traffic
  remain blocked while WireGuard is unavailable;
- restoring the endpoint permits a fresh WireGuard handshake;
- firewalld, Wi-Fi, PIA, and cleanup are healthy at the end.

Start while PIA Bazzite is connected through the normal Wi-Fi:

```bash
./tools/kill-switch-firewalld-restart-test.sh
```

Confirm with `FIREWALL`.

Do not interact with Plasma networking, firewalld, or PIA Bazzite while
the test is running.

Report:

`pia-kill-switch-firewalld-restart-test.txt`
