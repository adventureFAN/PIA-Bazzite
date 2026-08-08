# Real GUI connection integration — Stage 5C

Stage 5C connects the already simulated and real-host-tested fail-closed
orchestrator to the normal PIA Bazzite window. The existing VPN-only behavior
remains available because the session Kill Switch is optional.

## User-visible behavior

A checkable **Options → Use Kill Switch** action stores the preference.
Enabling it authorizes the restricted installed helper and verifies that no
production firewall table is already active. The disconnected state then shows
**VPN & Kill Switch ready**. The setting cannot be changed while the VPN is
connected.

With the setting disabled, the old NetworkManager connection path remains
unchanged and the connected state is deliberately blue: VPN active, Kill
Switch off.

## Protected connection order

The GUI worker performs these steps before it may report a protected
connection:

1. Prove a normal IPv4 path and record available IPv6 and direct TCP/UDP DNS
   paths as the disconnect baseline.
2. Create the private temporary PIA WireGuard configuration.
3. Read its exact numeric endpoint and discover the physical escape route.
4. Build and revalidate the strict connection plan.
5. Authorize the restricted helper session.
6. Enable and structurally verify `inet pia_bazzite_killswitch`.
7. Only then start NetworkManager WireGuard.
8. Verify both the VPN and the still-active firewall table.

If a failure happens after firewall preparation, the GUI never performs a
generic unlock. It rechecks the helper status where possible and displays
orange blocking or red uncertainty instead of claiming safety.

## Intentional disconnect order

A protected disconnect requires the baseline captured by the same running app
session. It verifies the firewall, stops and verifies the VPN while retaining
the lock, proves every previously available IPv4, IPv6 and direct DNS path is
blocked, and only then disables and verifies the firewall table.

The same safe release path is used when the user disables the setting after a
failed connection left the verified firewall lock active.

## Deliberate Stage-5C limits

- Protected live server switching is refused; it follows in Stage 6.
- Closing the app while protected and connected is refused. Safe handover to a
  restarted app follows in Stage 7.
- Closing while the VPN is down but the firewall lock is active is refused.
- A firewall lock found after an app restart has no matching in-memory probe
  baseline and therefore requires the documented Emergency Reset until Stage 7
  implements ownership and takeover.
- Reconnect after an unexpected tunnel loss remains Stage 6. Stage 5C keeps
  the verified lock active, hides stale public-IP/DNS values, and requires a
  deliberate safe release before a new manual connection.

The restricted broker idle limit is extended to twelve hours for a normal GUI
connection. It still accepts only the fixed protocol and exits when the app
closes, the request limit is reached, or the timeout expires.

## Unprivileged gate

Run:

```bash
cd $HOME/PIA-Bazzite
bash tools/kill-switch-connection-stage5c-self-test.sh
```

The gate does not use root, Polkit, networking, NetworkManager or nftables. It
must finish with:

```text
SELF-TEST PASSED
ALL STAGE-5C GUI INTEGRATION SELF-TESTS PASSED
No host firewall or VPN connection was changed by this self-test.
```

The updated helper must be installed again before the later real GUI test so
the installed checksum manifest and the twelve-hour restricted session match
the Stage-5C source.
