# PIA Bazzite guarded real-host kill-switch test

This is the first test that temporarily modifies the host nftables
ruleset and disconnects the real PIA WireGuard profile.

Safety measures:

- It creates only `table inet pia_bazzite_killswitch_test`.
- It never flushes or edits firewalld's tables.
- A root-owned systemd timer deletes the test table after 150 seconds.
- A shell cleanup handler removes the table during normal exit.
- `kill-switch-emergency-reset.sh` removes the table immediately.
- The existing PIA endpoint is allowed so NetworkManager can reconnect.

Before testing:

- Keep PIA Bazzite connected.
- Pause downloads, voice calls, games, and other network-sensitive work.
- Keep the terminal open.
- Optionally open a second terminal with this command ready:

  ```bash
  cd /home/alex/PIA-Bazzite
  ./tools/kill-switch-emergency-reset.sh
  ```

Start the test:

```bash
./tools/kill-switch-guarded-host-test.sh
```

The report is saved as:

`pia-kill-switch-guarded-host-test.txt`
