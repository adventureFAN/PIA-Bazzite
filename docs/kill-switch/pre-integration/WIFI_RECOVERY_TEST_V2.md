# PIA Bazzite guarded Wi-Fi recovery test v2

Corrections from the first test:

- disconnects the whole Wi-Fi device instead of one connection profile;
- prevents NetworkManager from selecting another saved WLAN;
- accepts a logically persistent WireGuard interface during link loss;
- does not require a new DHCPv4 exchange when a cached lease is reused;
- temporarily removes the PIA endpoint from the allow set;
- forces IPv4, IPv6, and DNS probes over the physical Wi-Fi interface;
- restores only the original Wi-Fi profile;
- releases the endpoint only after the protected-gap probes finish.

Start while PIA Bazzite is connected through the desired Wi-Fi:

```bash
./tools/kill-switch-wifi-recovery-test.sh
```

Confirm with `WIFI2`.

Do not reconnect Wi-Fi manually. NetworkManager may take up to 90
seconds to activate the original profile.

Report:

`pia-kill-switch-wifi-recovery-test-v2.txt`
