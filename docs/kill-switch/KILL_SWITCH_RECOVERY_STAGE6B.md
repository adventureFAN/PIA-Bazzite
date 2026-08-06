# Kill switch recovery Stage 6B

Stage 6B is the first real-host gate for the Stage-6 recovery boundary. It does
not enable automatic recovery or protected switching in the normal GUI.

## Real sequence

The guarded host test performs one complete production-table session:

1. prove ordinary IPv4 and optional IPv6/direct-DNS baselines;
2. create the initial private PIA WireGuard configuration;
3. prove a direct physical-interface path exists before the lock;
4. authorize and verify the installed production helper;
5. enable and verify the firewall before starting PIA;
6. start a continuous physical-interface leak sentinel;
7. force the NetworkManager WireGuard profile down without releasing the lock;
8. prove the ordinary IPv4, available IPv6, and direct DNS paths are blocked;
9. reactivate the exact existing profile UUID under the retained lock;
10. prepare a distinct second PIA configuration through the connected old VPN;
11. stop the old VPN, prove the blocked path again, retarget the allowlists, and
    start the new profile;
12. verify protected connectivity and the exact candidate endpoint;
13. intentionally stop the final VPN, prove the blocked path, stop and verify the
    leak sentinel, and only then deliberately release the firewall.

## Continuous direct-path sentinel

The sentinel runs under the explicitly cached `sudo` authorization and binds
fixed IPv4, optional IPv6, and direct-DNS probes to the physical interface with
`SO_BINDTODEVICE`. Its targets and ports are compiled into the script. It does
not accept arbitrary destinations or commands.

A direct IPv4 path must succeed before the firewall is enabled. During the
protected tunnel-loss, reconnect, and server-switch interval, any successful
physical-interface probe is treated as a leak. The driver returns a fail-closed
status and never deliberately disables the production table.

## Independent recovery

Before the real driver starts, a root-owned transient systemd timer is armed for
15 minutes. If the test cannot prove a safe deliberate unlock, the timer remains
armed. It stops the fixed `PIA Bazzite` profile first and then destroys only the
fixed `inet pia_bazzite_killswitch` table.

For an immediate deliberate recovery:

```bash
cd /home/alex/PIA-Bazzite
bash tools/kill-switch-recovery-stage6b-emergency-reset.sh
```

## Deliberate limits

- The normal GUI still does not reconnect automatically.
- The normal GUI still refuses protected server switching.
- Wi-Fi/LAN changes, NetworkManager restart, suspend/resume, application crash,
  and takeover of an existing lock remain separate gates.
- The host test requires two cached PIA regions with different numeric
  WireGuard server addresses.

## Stage 6B.1 sentinel startup correction

The first real Stage-6B run exposed a test-harness race before the forced tunnel
loss began. The root sentinel's pre-lock baseline result was atomically written
as a root-owned file in sticky `/tmp`. The non-root driver could read it but
could not remove it. At protected sentinel startup, the driver could therefore
briefly read that old successful baseline as though it were a new protected
sample.

Stage 6B.1 corrects that boundary in three independent ways:

- every atomically published sentinel result is chowned to the real invoking
  desktop user from sudo's validated `SUDO_UID` and `SUDO_GID`;
- the driver refuses to start if any stale result, stop, or temporary file
  remains after cleanup;
- an immediate genuine leak reports the exact successful probe counters and can
  no longer print a contradictory clean-sentinel message while stopping.

This correction changes only the real-host test harness. It does not relax the
production nftables rules, the fail-closed recovery orchestrator, or the
independent emergency reset.
