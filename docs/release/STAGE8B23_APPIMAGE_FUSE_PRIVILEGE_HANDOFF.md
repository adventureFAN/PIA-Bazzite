# Stage 8B.2.3 — AppImage FUSE privilege handoff

The first real 0.6.0 AppImage host gate established that the desktop user can read and verify the mounted helper bundle while root cannot traverse that normal AppImage FUSE mount on this Bazzite host. This is a valid FUSE permission model and must not be treated as a broken AppImage or a reason to change host-wide FUSE configuration.

The production install/update flow therefore no longer passes the mounted AppImage path directly across the privilege boundary. Immediately before `pkexec`, `PackagedHelperManager`:

1. verifies the exact mounted 0.6.0 helper manifest, file set, modes, and SHA-256 values;
2. copies only that fixed payload into a randomly named private `0700` directory under `/tmp` on the normal host filesystem;
3. verifies the staged payload again against the same manifest;
4. passes only the staged fixed installer path to `/usr/bin/pkexec --disable-internal-agent /usr/bin/bash`;
5. relies on the privileged installer to validate the staged manifest and hashes again before the fixed root-owned helper boundary is changed;
6. removes the private staging directory after success, denial, timeout, or installer failure.

The Stage-8B.2 host gate now proves this exact staging path is root-readable before uninstalling or changing an existing helper. Direct root readability of the FUSE mount is informational only and may legitimately be unavailable.

No VPN connection or production Kill Switch firewall is required for this handoff proof.
