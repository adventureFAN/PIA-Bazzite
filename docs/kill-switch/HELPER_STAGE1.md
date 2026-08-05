# Session Kill Switch – Helper Stage 1

Stage 1 introduces a restricted **test-only** helper and does not integrate it
with the PIA Bazzite application, polkit, NetworkManager, or the AppImage.

## Safety boundary

The stage-1 helper deliberately refuses to run in the host network namespace.
It can only be exercised through the isolated namespace test. This prevents an
accidental direct invocation from changing the host firewall.

The helper can manage only this fixed table:

`inet pia_bazzite_killswitch_helper_test`

There is no argument, environment variable, or configuration file that can
change the table name, chain name, VPN interface, nft executable, or accepted
command set.

## Fixed actions

- `status`
- `enable --interface NAME --endpoint ADDRESS:PORT`
- `add-endpoint --endpoint ADDRESS:PORT`
- `remove-endpoint --endpoint ADDRESS:PORT`
- `disable`
- `emergency-reset`

All output is one JSON object. Mutating operations first ask nftables to check
the complete transaction and apply the same transaction only after that check
succeeds.

## Input restrictions

- Physical interface names use a strict Linux-interface allowlist and are
  limited to 15 characters.
- `lo` and `piabazzite` cannot be supplied as physical interfaces.
- Endpoints must be numeric IPv4 or bracketed IPv6 addresses plus a decimal UDP
  port from 1 to 65535.
- Hostnames, shell metacharacters, loopback, multicast, and unspecified
  addresses are rejected.
- At most 8 physical interfaces and 32 endpoints are accepted.
- The helper invokes only `/usr/sbin/nft`, `/usr/bin/nft`, or `/sbin/nft` with an
  argument array, a fixed environment, and no shell.

## Automated tests

The complete unprivileged self-test does not change networking:

```bash
./tools/kill-switch-helper-stage1-self-test.sh
```

It includes the helper unit tests and the existing PIA Bazzite v0.5.0 regression self-test.

The integration test creates three temporary network namespaces and runs the
helper only inside the isolated client namespace:

```bash
./tools/kill-switch-helper-stage1-namespace-test.sh
```

It verifies strict input rejection, nftables transaction checks, IPv4/IPv6
blocking, exact UDP endpoint access, VPN-interface access, idempotent endpoint
updates, status verification, repeated disable, cleanup, and absence of the test
table on the host.

The report is written to:

`test-results/kill-switch/stage1-helper/pia-kill-switch-helper-stage1-namespace-test.txt`

## Not implemented in this stage

- no polkit policy;
- no root-owned installation path;
- no call from the PySide6 application;
- no production table name;
- no real PIA endpoint or NetworkManager profile;
- no tray, Live Log, state-machine, or AppImage integration.

The helper source is still located in the user-writable project directory.
Therefore it must not be exposed through polkit or treated as the final
privileged installation. Stage 2 will define and test the root-owned install
layout and authorization boundary.
