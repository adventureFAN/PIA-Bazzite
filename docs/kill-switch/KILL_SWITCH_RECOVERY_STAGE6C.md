# Kill switch recovery and protected switching — Stage 6C

Stage 6C connects the Stage-6A recovery orchestrator, which passed the real
Stage-6B host and leak-sentinel gate, to the normal PIA Bazzite window and tray.
The production firewall rules and helper protocol are unchanged.

## Unexpected tunnel loss

While a protected connection belongs to the current app session, the GUI keeps
three pieces of recovery state in memory: the NetworkManager profile UUID, the
pre-connection ordinary-path baseline, and the exact verified firewall route.

When the status timer observes an unexpected connected-to-disconnected change:

1. the user-visible state becomes orange (`Safely blocked`);
2. the app schedules exactly one automatic recovery attempt;
3. the helper session verifies the retained production firewall table;
4. every ordinary path captured before the original connection must still be
   blocked;
5. the exact endpoint/interface allowlists are re-verified;
6. only then may NetworkManager reactivate the same profile UUID;
7. VPN and firewall are verified together before green is restored.

A failed automatic attempt never opens the firewall. The orange state offers a
manual protected reconnect action in both the main button and tray. There is no
unbounded retry loop.

## Protected server switch

No permanent switch button is added. Selecting a different location in the main
combo box or connected tray menu opens one explicit confirmation. After
confirmation, the candidate private WireGuard configuration is prepared through
the still-connected old VPN. The tested offline transition then stops the old
VPN, proves ordinary paths blocked, retargets the firewall, starts the new
profile, and verifies both layers.

The current Stage-6C GUI deliberately requires the replacement endpoint to use
the same physical interface as the active protected route. Wi-Fi/LAN changes are
left for their dedicated recovery gate. If the old VPN has already stopped and a
switch fails, the GUI discards its in-memory route plan rather than guessing and
refuses unsafe recovery. The production lock remains active.

## UI correctness

Internal connect, reconnect, switch, and deliberate disconnect completions update
the cached NetworkManager state before the normal status refresh. This removes
the old cosmetic log line that incorrectly described an app-started connection
as an external NetworkManager action.

## Unprivileged gate

Run:

```bash
cd $HOME/PIA-Bazzite
bash tools/kill-switch-recovery-stage6c-self-test.sh
```

The self-test performs syntax, static safety, translation, and all previous
regression checks. It does not use sudo, Polkit, networking, NetworkManager,
nftables, or the Stage-6B leak sentinel.
