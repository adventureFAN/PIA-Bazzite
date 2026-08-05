# Stage 2D.2 – Production-like nftables structure

Stage 2D.2 replaces per-interface rule generation with fixed nftables sets while
keeping the helper inside the isolated network-namespace safety boundary.

## Fixed candidate structure

The helper still uses the isolated table name:

`pia_bazzite_killswitch_helper_test`

The table now contains:

- `physical_interfaces` (`ifname`)
- `allowed_endpoints_v4` (`ipv4_addr . inet_service`)
- `allowed_endpoints_v6` (`ipv6_addr . inet_service`)
- one `output` base chain at priority `-100`
- loopback allowance
- DHCPv4, DHCPv6, and required IPv6 neighbour-discovery allowance on the
  selected physical interfaces
- exact UDP endpoint allowance on the selected physical interfaces
- unrestricted output through `piabazzite`
- a final reject rule for every other output path

The helper never accepts a table name, set name, chain name, rule fragment, or
executable path from the caller.

## Atomic updates

Protocol v1 adds two fixed actions:

- `set-interfaces --interface ...`
- `set-endpoints --endpoint ...`

Each action produces one nftables batch. The interface action flushes and
repopulates only the fixed `ifname` set. The endpoint action flushes and
repopulates both endpoint-family sets in one transaction. A failed nftables
check prevents the apply step.

Incremental `add-endpoint` and idempotent `remove-endpoint` remain available for
the later server-switch sequence.

## Verification

`status` verifies table ownership comments, set types, chain properties, and all
required rule markers. It advertises the supported update capabilities and a
fixed `table_generation` value.

## Safety boundary

This stage intentionally does not:

- operate in the initial host network namespace;
- use the final production table name;
- connect to NetworkManager or the PIA API;
- connect to the PySide6 application;
- install a persistent custom Polkit policy.

The real nftables test runs only inside temporary namespaces with two simulated
physical uplinks and one simulated VPN interface.
