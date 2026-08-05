# Stage 2E – Installation and authorization security boundaries

Stage 2E hardens the root-owned helper installation before any application
integration or host-network operation is enabled.

## Verify before import

The installed launcher is now a standalone Python `-I` bootstrap. Before it
adds the installed package directory to `sys.path` or imports any helper module,
it verifies:

- execution from the fixed installed launcher path;
- a non-root `PKEXEC_UID` while running with effective UID 0;
- root ownership and non-writable modes of all fixed directories;
- regular-file type, root ownership, exact mode, and single hard link for every
  installed file;
- exact manifest shape and identity;
- installation format 1, helper stage 2, and protocol version 1;
- the exact installed package file set;
- SHA-256 of the launcher and every Python module.

Handled bootstrap failures use the same protocol-v1 JSON envelope with the
`installation-boundary`, `privilege`, or `bootstrap-failure` error kind.

## Installer and uninstaller

The stage-2 installer remains explicitly root-invoked and fixed to:

`/usr/local/libexec/pia-bazzite/`

It now uses a non-blocking installation lock so two operations cannot modify the
same installation concurrently. Its manifest records the installation format,
helper stage, protocol version, and exact checksums.

Before removing a single known file, the uninstaller preflights all known paths.
A symlink, non-regular target, or non-root-owned target aborts the whole removal
before any helper file is deleted. The uninstaller never uses recursive removal
and deliberately leaves unknown files untouched.

## Tests

The unprivileged test checks syntax, unit tests, static installer boundaries,
and the existing v0.5.0 regression test:

```bash
./tools/kill-switch-helper-stage2e-self-test.sh
```

The interactive test installs the root-owned helper and checks:

1. direct unprivileged execution is refused;
2. a clean bootstrap reaches the existing host-network refusal;
3. cancelling the graphical Polkit dialog prevents execution;
4. checksum tampering is rejected before package import;
5. unsafe file modes are rejected;
6. a wrong helper-stage manifest is rejected;
7. a symlink causes uninstall to abort before any known file is removed;
8. an unknown root-owned sentinel survives normal uninstall;
9. no helper nftables table appears on the host.

```bash
./tools/kill-switch-helper-stage2e-security-test.sh
```

The denial test first revokes temporary Polkit authorizations and invokes
`pkexec` with its internal text agent disabled. The user must deliberately click
Cancel in the KDE authentication dialog. A 60-second timeout prevents the test
from hanging indefinitely. Depending on the desktop authentication agent,
`pkexec` may report this as exit code 126 (dialog dismissed) or as exit code 127
with `Not authorized`. Both outcomes are accepted only when the helper did not
run and the host firewall remains unchanged.

## Still disabled

Stage 2E does not:

- enable helper operation in the host network namespace;
- use the final production table name;
- install a custom Polkit policy;
- connect the helper to the PySide6 application;
- call NetworkManager or the PIA API;
- create or modify host firewall rules.
