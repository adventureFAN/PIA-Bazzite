# Kill Switch crash takeover Stage 7C.4

**Status:** Authoritative real crash/restart takeover proof for the final Stage-7 implementation.


The Stage-7C.3 host report did not prove that the restarted GUI lost its
restricted session. Its privileged `/proc` probe searched only processes whose
command line contained the fixed helper path. The same helper path was also an
argument of the probe itself, so the failure summary was contaminated by the
probe's own `sudo` and Python process chain while other legitimate peer
processes could be omitted.

Stage 7C.4 corrects only this external proof boundary. The already-tested
production takeover code remains unchanged.

## Corrected peer-pipe proof

The root-visible probe now:

1. records the restarted GUI's pipe descriptors;
2. excludes the probe process and its complete ancestor chain;
3. scans every process that shares at least one GUI pipe, without filtering by
   command-line text first;
4. accepts only one root-owned process whose stdin, stdout, and stderr are three
   distinct pipes paired with the GUI;
5. reports UID, executable, command line, ancestry, and every shared pipe on
   failure.

The fixed helper path is still recorded as identity evidence, but it is no
longer the discovery filter. This matters because `pkexec` may replace,
reparent, or rewrite the visible process identity while leaving the authenticated
transport and its exact private pipes alive.

Success still requires the same root transport PID, rotated recovery record,
NetworkManager profile, verified firewall route, and independent direct-path
sentinel to remain stable together before normal GUI disconnect is allowed.

Run the unprivileged gate first:

```bash
bash tools/kill-switch-crash-stage7c4-self-test.sh
```

Then repeat the real crash takeover:

```bash
bash tools/kill-switch-crash-stage7c4-host-test.sh
```

For immediate deliberate cleanup after a fail-closed stop:

```bash
bash tools/kill-switch-crash-stage7c4-emergency-reset.sh
```
