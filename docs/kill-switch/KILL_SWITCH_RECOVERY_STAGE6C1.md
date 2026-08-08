# Kill switch GUI recovery — Stage 6C.1

Stage 6C.1 adds two final gates before Stage 6 is accepted.

## Unambiguous security wording

The German and English Live Log texts now distinguish three different actions:

- **system authorization**: the restricted helper session is being authorized;
- **firewall endpoint exceptions**: only the exact VPN endpoint exceptions are
  changed while the blocking rule remains active;
- **deliberate unlock**: the verified firewall lock is removed only during a
  conscious disconnect.

The former German wording `Der Kill Switch wird freigegeben` was removed because
it could be read as opening or disabling the firewall.

## Independent real-GUI sentinel gate

The real Stage-6C.1 test launches the ordinary project GUI and observes it from a
separate test process. Before the app starts, the test proves which direct paths
work on the physical interface. It arms an independent systemd safety reset, then
waits for the production nftables table to appear and verifies its complete
owned structure before starting the root-bound `SO_BINDTODEVICE` sentinel.

The test then:

1. waits for a normal green protected connection in the GUI;
2. forces one external NetworkManager tunnel loss;
3. observes the GUI's automatic protected reconnect;
4. waits for the user to confirm a switch to a different server;
5. verifies the production table continuously during both transitions;
6. rejects one successful direct IPv4, IPv6, DNS/TCP, or DNS/UDP fallback;
7. stops and verifies the sentinel only after the new protected VPN is stable;
8. requires the user to save the GUI Live Log;
9. waits for a deliberate GUI disconnect, absent firewall table, and restored
   ordinary connectivity before cancelling the safety reset.

The observation driver contains no firewall-disable or table-destroy operation.
On any failure after the lock has appeared, the independent reset remains armed
and the documented Emergency Reset is shown.

## Unprivileged gate

Run:

```bash
cd $HOME/PIA-Bazzite
bash tools/kill-switch-recovery-stage6c1-self-test.sh
```

This gate performs syntax, static ordering, wording, translation, and all prior
regression checks. It does not use sudo, Polkit, networking, NetworkManager,
nftables, the GUI, or the leak sentinel.
