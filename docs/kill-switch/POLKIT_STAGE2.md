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

## Stage 2C root-owned restricted helper

Stage 2C installs the existing restricted stage-1 helper under the fixed path:

`/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper`

The adjacent Python package and a checksum manifest are installed under the
same root-owned directory. The installed launcher uses Python isolated mode
(`-I`), accepts only a valid non-root `PKEXEC_UID`, clears the inherited
environment, verifies ownership, permissions, hard-link counts, fixed paths,
and every installed checksum before importing the helper command path.

The helper still refuses the host network namespace and still manages only the
fixed test table `pia_bazzite_killswitch_helper_test`. Stage 2C therefore does
not enable a production host kill switch.

The unprivileged test is network-free:

```bash
./tools/kill-switch-polkit-stage2-helper-self-test.sh
```

The authorization test installs the helper, creates temporary network
namespaces, invokes the fixed installed helper through graphical `pkexec`,
verifies that the namespace firewall blocks ordinary IPv4 and IPv6 while the
simulated VPN remains available, then removes both the table and the installed
helper:

```bash
./tools/kill-switch-polkit-stage2-helper-namespace-test.sh
```

The namespace test deliberately performs the final firewall cleanup directly
from its root-owned test harness. This keeps the graphical authorization test
to one helper invocation while the already completed stage-1 test remains the
full lifecycle test for `status`, endpoint updates, `disable`, and
`emergency-reset`.

### Stage 2C namespace authorization bridge

The graphical authorization request must originate from the active desktop
session. Entering a network namespace and changing user identity before calling
`pkexec` detaches the request from KDE's registered authentication agent and can
cause `pkexec` to fall back to its textual agent.

The corrected namespace test therefore calls `pkexec` from the normal desktop
session with `--disable-internal-agent`. A temporary root-owned test bridge then
enters only a namespace matching `pia-h2-client-<digits>` and invokes the fixed
installed helper with one entirely hard-coded `enable` request. It accepts no
helper action, interface, endpoint, executable path, or shell command from the
user. The bridge is removed explicitly at the end of the test and is not part
of the production helper design.
