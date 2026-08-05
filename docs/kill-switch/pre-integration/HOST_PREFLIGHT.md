# PIA Bazzite guarded host-test preflight

This package prepares the next session kill-switch test.

The preflight is read-only. It does not create nftables rules, disconnect
the VPN, or change NetworkManager.

Before running it:

1. Start PIA Bazzite.
2. Connect to a PIA location.
3. Leave PIA Bazzite running.
4. Run:

   ```bash
   ./tools/kill-switch-host-preflight.sh
   ```

The report is saved as `pia-kill-switch-host-preflight.txt`.

Do not run a real host firewall test until the report has been reviewed.

`kill-switch-emergency-reset.sh` is a harmless emergency helper for the
later guarded test. At this stage it should simply report that no temporary
test table exists.
