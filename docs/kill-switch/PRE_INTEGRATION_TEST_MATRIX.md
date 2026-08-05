# Session Kill Switch – Pre-Integration Test Matrix

These tests validate the standalone nftables and recovery design before its
integration into the PIA Bazzite application, privileged helper, polkit policy,
UI state machine, and AppImage packaging.

## Test results

| Test | Raw result | Security assessment | Main evidence |
|---|---:|---|---|
| Guarded host tunnel failure | 38 pass, 0 warnings, 0 failures | Passed | Tunnel removed while the kill-switch table remained active; IPv4, IPv6, and direct DNS were blocked; WireGuard reconnected successfully. |
| Server switch | 43 pass, 0 warnings, 0 failures | Passed | New endpoint admitted before the switch; old endpoint removed afterward; forced traffic to the retired endpoint was blocked. |
| firewalld reload | 39 pass, 0 warnings, 0 failures | Passed | Independent nftables table survived `firewall-cmd --reload`; fallback traffic remained blocked. |
| Application crash | 38 pass, 0 warnings, 0 failures | Passed | The AppImage process was terminated with `SIGKILL`; the kill-switch table survived; traffic remained blocked after tunnel removal; VPN recovery succeeded while the GUI was closed. |
| Wi-Fi outage and recovery v2 | 50 pass, 0 warnings, 0 failures | Passed | Complete Wi-Fi device loss; no switch to another saved WLAN; original WLAN restored; forced IPv4, IPv6, and DNS-like traffic hit the block rule before VPN recovery. |
| Suspend and resume | 48 pass, 0 warnings, 1 failure | Security passed; timing measurement false negative | The nftables table, safety timer, Wi-Fi, and firewalld survived suspend/resume; forced post-resume fallback traffic was blocked; WireGuard recovered. The single failure came from measuring suspend duration before `systemctl suspend` completed asynchronously. |
| Failed WireGuard reconnect | 40 pass, 0 warnings, 1 failure | Security passed; UDP test false negative | No fresh handshake while the endpoint was withheld; IPv4 and IPv6 fallback were blocked; the block counter increased; VPN recovered after endpoint restoration. The DNS failure only detected a successful local UDP `send()`, not a received DNS response. |
| Wi-Fi to LAN and back | 51 pass, 0 warnings, 2 failures | Security passed; handshake expectation false negatives | WireGuard endpoint traffic moved over Ethernet and back to Wi-Fi; direct IPv4, IPv6, and valid DNS responses were blocked on both interfaces. The two failures incorrectly required an immediate new handshake although encrypted traffic continued through the existing WireGuard session. |
| Automatic safety reset | 34 pass, 0 warnings, 0 failures | Passed | Independent root-owned timer removed the blocking table, reactivated PIA, obtained a fresh handshake, and restored VPN connectivity without manual intervention. |
| NetworkManager restart | 50 pass, 0 warnings, 0 failures | Passed | Independent kill-switch table and safety timer survived a complete NetworkManager restart; physical fallback remained blocked; Wi-Fi and WireGuard recovered. |
| Full firewalld restart | 50 pass, 0 warnings, 0 failures | Passed | firewalld was replaced by a new process; the independent nftables table survived; IPv4, IPv6, DNS, and ordinary fallback remained blocked; WireGuard recovered. |

## Validated scenarios

- Unexpected WireGuard tunnel loss
- Failed WireGuard reconnection
- VPN server and endpoint replacement
- Retirement of the previous endpoint
- Application crash with `SIGKILL`
- Complete Wi-Fi loss and recovery
- Wi-Fi to Ethernet and Ethernet to Wi-Fi transitions
- System suspend and resume
- NetworkManager service restart
- firewalld reload
- Complete firewalld process restart
- Root-owned automatic safety reset
- Forced physical IPv4 fallback
- Forced physical IPv6 fallback
- Direct DNS-response checks
- Cleanup of temporary nftables tables and systemd timers

## Known limitations of these tests

These tests validate the standalone firewall model and recovery behaviour.
They do not yet validate:

- the final restricted privileged helper;
- polkit authorization and denial handling;
- communication between the PySide6 application and the helper;
- application states `Ready`, `Active`, `Blocking`, and `Error`;
- tray icon and Live Log behaviour;
- adoption of an existing kill-switch table after application restart;
- AppImage installation of helper and polkit files;
- failure handling during the real PIA API bootstrap process.

Those areas must be tested again after each integration stage.

## Raw reports

The original reports are stored in:

`test-results/kill-switch/pre-integration/`

The individual test instructions are stored in:

`docs/kill-switch/pre-integration/`
