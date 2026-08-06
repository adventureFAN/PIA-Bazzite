# Kill-switch connection orchestration — Stage 5A

Stage 5A adds a small, deterministic and fully simulated connection
orchestrator. It does not call PIA, NetworkManager, Polkit or nftables during
its self-test.

## Safety order

When the optional kill switch is enabled, the orchestrator enforces this order:

1. Validate the already-created private `piabazzite.conf` file, physical
   interfaces and exact numeric WireGuard endpoint. The single endpoint inside
   the configuration must exactly match the firewall allowlist.
2. Open the restricted single-authorization helper session.
3. Atomically enable and verify the firewall lock.
4. Only then allow the VPN backend to start WireGuard.
5. Verify both the active VPN and the still-active firewall lock.

If authorization or firewall preparation fails, NetworkManager is never
called. If VPN startup fails, the verified firewall lock remains active. If a
post-connect verification fails, the VPN is disconnected while the firewall
lock remains untouched.

## Deliberate limits

Stage 5A does not yet:

- discover the current physical interface;
- change the real GUI connection path;
- install or activate the production helper on the host;
- intentionally disconnect and unlock;
- switch between VPN servers while already connected.

Server switching is explicitly refused by this stage so that a later stage can
implement the already-tested "new endpoint first, old endpoint later" sequence
without silently weakening protection.

When the kill switch is disabled, the orchestrator bypasses the privileged
session and preserves the existing VPN-only behavior.
