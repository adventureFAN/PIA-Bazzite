# PIA Bazzite guarded suspend/resume test v2

This test suspends the computer while a separate nftables kill-switch
table is active.

It verifies that:

- the system really entered suspend;
- the nftables table survived suspend and resume;
- the root-owned recovery timer remained active;
- the original Wi-Fi profile returned;
- a changed WireGuard endpoint can be admitted safely;
- forced IPv4, IPv6, and DNS traffic is blocked in a controlled
  post-resume gap;
- WireGuard completes a fresh handshake after endpoint release;
- the temporary rules and recovery timer are removed afterward.

Before starting:

1. Connect PIA Bazzite through the normal Wi-Fi.
2. Save work and pause network-sensitive applications.
3. Start the test:

   ```bash
   ./tools/kill-switch-suspend-resume-test.sh
   ```

4. Confirm with `SUSPEND`.
5. After the screen turns off, wait about 20 to 30 seconds.
6. Wake the computer and log in if required.
7. Do not reconnect Wi-Fi or VPN manually.

Report:

`pia-kill-switch-suspend-resume-test.txt`

## Version 2 correction

The first package used `systemctl status sleep.target` as a preflight check.
An inactive target makes that command return a non-zero status even when
suspend support is available.

Version 2 checks that `suspend.target` is loaded. The actual suspend operation
continues to use `systemctl suspend`.
