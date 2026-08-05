# Kill Switch Client – Stage 3A

Stage 3A adds the unprivileged Python boundary that the PIA Bazzite application
will later use to communicate with the installed restricted helper.

This stage does **not** connect the client to the GUI and does not invoke a real
helper during its self-test.

## Fixed invocation boundary

The client can invoke only:

```text
/usr/bin/pkexec
  --disable-internal-agent
  /usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper
  <fixed protocol action and validated arguments>
```

It never uses a shell, does not accept an executable path from the caller, and
does not expose a generic arbitrary-command method.

The internal terminal authentication agent is disabled. A desktop Polkit agent
must authorize privileged calls; the client must not fall back to reading a
password from the terminal.

## Client-side distinctions

The client reports these situations separately:

- helper installation missing or unsafe;
- fixed `pkexec` binary unavailable or unsafe;
- Polkit authorization cancelled or denied;
- helper invocation timed out;
- malformed, mixed, oversized, or missing JSON output;
- incompatible schema, protocol, or helper stage;
- structured helper error such as validation, nftables, verification, or
  installation-boundary failure.

## No false protection state

A successful process exit is not enough to claim protection. An active state is
accepted only when the helper response says all of the following:

- `state: active`
- `present: true`
- `verified: true`
- `problems: []`

Likewise, deliberate disable and emergency reset must return a verified disabled
state with the helper table absent.

## Environment handling

The client preserves the desktop-session variables needed by the graphical
Polkit agent, but removes loader, Python, AppImage, and sudo environment
variables that must not influence `/usr/bin/pkexec`.

## Current limit

Stage 3A is tested only with a fake process runner. Stage 3B will install the
real helper in the namespace laboratory and exercise the same client through a
graphical Polkit authorization flow and real nftables transactions.
