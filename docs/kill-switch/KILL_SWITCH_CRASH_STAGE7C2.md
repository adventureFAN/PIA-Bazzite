# Kill Switch crash takeover Stage 7C.2

**Status:** Historical external-proof experiment. Its ancestry and command-line assumptions are superseded by Stage 7C.4; it did not replace production takeover logic.


The repeated Stage-7C.1 host stop did not show a leak, firewall change, VPN
change, or invalid recovery record. It showed that the external driver could
see the rotated record but could not find the restricted helper through its
unprivileged `/proc/<pid>/cmdline` scan.

That process proof had an ambiguity: after `pkexec` completes, the session is a
root-owned process. A hardened Linux `/proc` view may refuse an unprivileged
read of that command line. The old driver treated both "not present" and
"present but unreadable" as the same result. The clean-start observation could
still see the pre-authorization `pkexec` command, so it did not expose this
ambiguity.

## Privileged process proof

Stage 7C.2 keeps the production app logic from Stage 7C.1 and corrects the real
host-test boundary. After the recovery record rotates, the driver first tries
the ordinary read-only process scan. If that cannot identify the helper, it
uses the host test's already-authorized `sudo -n` boundary to read `/proc` and
requires all of the following:

1. the fixed installed session path appears in the root-visible command line;
2. the process remains an exact descendant of the restarted GUI PID;
3. the same helper PID and rotated recovery record remain stable together;
4. NetworkManager, the exact firewall route, and the leak sentinel remain
   continuously valid.

The host wrapper keeps only the existing sudo timestamp alive. It does not add
another firewall capability to the application and does not change production
runtime behavior.

If the root-visible probe also finds no retained helper, the test still stops
fail-closed. That result would prove a real session-lifetime problem rather than
an unprivileged process-visibility false negative.

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c2-self-test.sh
```

Then run the real host test:

```bash
bash tools/kill-switch-crash-stage7c2-host-test.sh
```

For an immediate deliberate reset after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c2-emergency-reset.sh
```
