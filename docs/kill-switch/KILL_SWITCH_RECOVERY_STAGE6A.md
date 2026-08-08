# Tunnel recovery and protected server-switch orchestration — Stage 6A

Stage 6A adds the deterministic fail-closed core for Etappe 6. It does not yet
activate automatic reconnect or protected server switching in the normal GUI.
The purpose of this stage is to prove all safety orderings with fakes before
NetworkManager, PIA, Polkit, or the production nftables table are touched again.

## Protected reconnect

One reconnect attempt may use only the already existing inactive NetworkManager
WireGuard profile. The orchestrator:

1. validates the stored profile UUID and the exact route allowlist;
2. authorizes the restricted helper session and verifies the production lock;
3. proves that NetworkManager currently reports the VPN as down;
4. proves every path captured before the original connection is blocked;
5. updates and verifies the exact physical-interface and endpoint allowlists;
6. reactivates the existing profile by UUID;
7. verifies the VPN and firewall lock together.

No failure path disables the firewall. A failed reconnect therefore remains in
the orange, blocked state instead of falling back to the ordinary connection.

## Protected server switch

The new private WireGuard configuration is created while the old VPN still
works. The safety boundary then performs an intentionally offline transition:

1. verify the candidate configuration, old VPN, and active firewall lock;
2. stop and verify the old VPN without changing the firewall;
3. prove the ordinary IPv4, available IPv6, and direct DNS paths are blocked;
4. resolve the physical route to the new numeric endpoint while offline;
5. extend the firewall allowlists to the old/new union;
6. atomically retire the old endpoint and old interface from those sets;
7. start the new NetworkManager WireGuard profile;
8. verify the new VPN and exact replacement firewall route together.

The short offline interval is deliberate. It avoids trying to infer a privileged
WireGuard fwmark while the old tunnel is active and, more importantly, avoids
any moment in which ordinary traffic is allowed.

If any step after the old VPN stops fails, the firewall lock remains active. The
new VPN is not started until the block proof and exact replacement allowlists
have both passed.

## Deliberate Stage-6A limits

- The GUI still refuses protected server switches.
- The GUI does not yet start automatic reconnect attempts.
- No real tunnel is interrupted by this stage.
- The real host recovery and server-switch tests follow in Stage 6B.
- Normal GUI integration, confirmations, timers, and the cosmetic external-
  connection log correction follow only after those real tests pass.

## Unprivileged gate

Run:

```bash
cd $HOME/PIA-Bazzite
bash tools/kill-switch-recovery-stage6a-self-test.sh
```

It must finish with:

```text
SELF-TEST PASSED
ALL STAGE-6A RECOVERY ORCHESTRATION SELF-TESTS PASSED
No host firewall or VPN connection was changed by this self-test.
```
