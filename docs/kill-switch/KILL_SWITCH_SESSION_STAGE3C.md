# Stage 3C – Single-authorization helper session

Stage 3C adds an optional session client above the existing one-shot
`KillSwitchClient`.

## Purpose

A normal helper call uses one `pkexec` process per action. That is secure, but a
multi-step workflow can produce several graphical authentication dialogs.

`KillSwitchSessionClient` instead opens one restricted privileged broker:

```text
PIA Bazzite
  -> pkexec (one graphical authorization)
  -> root-owned session broker
  -> fixed JSON-lines protocol
  -> existing validated helper actions
```

The broker does not provide a shell and does not accept executable paths,
table names, nftables source, or arbitrary command lines. It accepts only the
existing fixed helper actions and their structured interface/endpoint fields.

## Safety properties

- The broker is installed root-owned under `/usr/local/libexec/pia-bazzite/`.
- The launcher verifies every installed file and manifest checksum before
  importing the broker package.
- Direct `sudo` or root execution is refused; a non-root `PKEXEC_UID` is
  required.
- The environment is reduced before package import.
- Requests use monotonically increasing integer IDs.
- Every response must come from the same broker PID.
- Input frames, request counts, and idle time are bounded.
- The broker exits on explicit close, pipe EOF, idle timeout, or request limit.
- Existing helper validation and nftables verification remain authoritative.
- No local Polkit authorization rule is installed.

## User experience

One session start may display one graphical Polkit dialog. `status`, `enable`,
endpoint/interface updates, and `disable` can then reuse the same broker until
it is closed. A new application session requires a new authorization.

## Scope

The Stage 3C real test still uses only the fixed candidate table inside
temporary network namespaces. It does not modify the host firewall,
NetworkManager, or the real PIA profile.
