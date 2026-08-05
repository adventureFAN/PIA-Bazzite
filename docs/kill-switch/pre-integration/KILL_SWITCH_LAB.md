# PIA Bazzite session kill-switch lab

This package contains two early safety tests for the planned session kill
switch. It does **not** integrate a kill switch into PIA Bazzite.

## 1. Preflight

```bash
./tools/kill-switch-preflight.sh
```

The preflight only reads system information. It does not use PIA, change
NetworkManager, or create firewall rules. Its report is written to
`pia-kill-switch-preflight.txt`.

## 2. Isolated namespace test

```bash
./tools/kill-switch-namespace-test.sh
```

The script asks for `sudo` automatically. It creates three temporary Linux
network namespaces:

- an isolated client;
- a simulated ordinary internet connection;
- a simulated VPN interface named `piabazzite`.

The prospective nftables rules exist only inside the temporary client
namespace. The test checks IPv4, IPv6, UDP endpoint access, DNS-like UDP,
tunnel loss, fallback prevention, counters, and deliberate reset.

The namespaces are deleted automatically, even when a test fails or the script
is interrupted.

## What this test does not prove

Passing this lab confirms the basic firewall rule model. It does not yet prove
correct behavior with the real PIA API, NetworkManager transitions, server
switching, sleep/resume, application crashes, or a host reboot. Those require a
separate guarded integration test before the feature can be released.
