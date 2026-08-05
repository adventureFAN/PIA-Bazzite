# Session Kill Switch – Polkit Stage 2

Stage 2 verifies the authorization and installation boundary before the real
kill-switch helper is exposed to the PIA Bazzite application.

## Stage 2A preflight

The host preflight confirms that Bazzite provides `pkexec`, `pkaction`, `nft`,
Python, and a graphical KDE Polkit authentication agent. It also confirms that
`/usr` is read-only while `/usr/local` resolves into persistent writable state
under `/var`. The reproducible read-only check is:

```bash
./tools/kill-switch-polkit-stage2-preflight.sh
```

## Stage 2B network-free authorization probe

The stage-2 probe is intentionally separate from the nftables helper. It cannot
change networking and contains no network, NetworkManager, subprocess, or
nftables execution.

The explicit test installer copies it to the fixed path:

`/usr/local/libexec/pia-bazzite/pia-bazzite-auth-probe`

The installed file and its two installation directories must be owned by
`root:root` and must not be group- or world-writable. The probe refuses to run
from another path, as a normal user, without a valid `PKEXEC_UID`, or if its
ownership checks fail.

Stage 2B uses Polkit's default `org.freedesktop.policykit.exec` action. No
custom policy or authorization rule is installed yet. This keeps the test small
and requires administrator authentication for the installed fixed program.

## Tests

The unprivileged self-test performs syntax, static safety, probe behavior, and
stage-1 helper regression tests without using `sudo`, `pkexec`, networking, or
nftables:

```bash
./tools/kill-switch-polkit-stage2-self-test.sh
```

The authorization test:

1. rejects invalid and unprivileged direct calls;
2. installs the probe as a root-owned regular file;
3. invokes that exact installed path through `pkexec`;
4. verifies JSON evidence of root execution, `PKEXEC_UID`, ownership, and the
   absence of network/nftables behavior;
5. removes the installed probe again.

```bash
./tools/kill-switch-polkit-stage2-auth-test.sh
```

The test deliberately uses `sudo` only for installation and removal. The actual
runtime authorization boundary is tested through the graphical Polkit prompt.

## Not implemented in this sub-stage

- no custom `.policy` action;
- no relaxed or cached authorization;
- no production nftables table;
- no installation of the real stage-1 helper;
- no AppImage or PySide6 integration;
- no NetworkManager or PIA API access.
