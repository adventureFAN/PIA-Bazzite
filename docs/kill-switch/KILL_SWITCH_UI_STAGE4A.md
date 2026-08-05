# Kill-switch UI state model — stage 4A

Stage 4A introduces the read-only presentation model used by the future
PIA Bazzite kill-switch integration.  It does not open the privileged session,
call Polkit, change NetworkManager, or apply nftables rules.

## Four user-visible states

| State | Meaning | Tray color | Trust rule |
|---|---|---|---|
| Ready | VPN disconnected and no firewall lock is active | Neutral gray | Never claims protection |
| Active | VPN connected and the helper table is present and verified | Green | Protection is guaranteed only after full verification |
| Blocking | VPN unavailable while the verified helper table remains active | Orange | Normal internet traffic remains blocked |
| Error | The expected protection cannot be verified | Red | The app must not continue as though protection were active |

The neutral gray is theme-aware: light gray on a dark desktop and dark gray on
a light desktop.  The application/window icon remains permanently green.

## Conservative derivation

`pia_bazzite.kill_switch_state` derives a UI state from a small immutable
observation.  A connected VPN without a present, verified firewall table is an
error.  A present but unverified table, a helper-reported problem, or an
explicit error also produces the red Error state.

Only a present and verified table may produce Active or Blocking.

## Safe preview

The preview tool renders all four states and their Live Log messages without
using the helper or any network component:

```bash
./.venv/bin/python tools/pia-bazzite-stage4a-state-preview.py
```

Optional arguments:

```bash
./.venv/bin/python tools/pia-bazzite-stage4a-state-preview.py \
  --language de \
  --theme dark
```

The tool imports no NetworkManager, helper-client, session-client, socket, or
subprocess module.  It is a visual simulation only.

## Scope boundary

Stage 4A does not yet:

- install or query the privileged helper;
- open a Polkit session;
- modify the main VPN connect/disconnect workflow;
- adopt an existing firewall table;
- show a persistent production error banner;
- change the real server-switch workflow.

Those behaviors remain for later stage-4 and stage-5 integration steps.
