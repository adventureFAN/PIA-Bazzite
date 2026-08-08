# Stage 8B.2 — real 0.6.0 AppImage helper host gate

Stage 8B.2 takes the Stage-8B packaged-helper design through the actual AppImage execution path on Bazzite before the broader release-candidate regression.

## Release-candidate proof

The host gate:

1. builds `PIA-Bazzite-0.6.0-x86_64.AppImage` through the Ubuntu 22.04 Podman path used to mirror the GitHub release environment;
2. verifies a portable SHA-256 sidecar and `--version` output;
3. extracts the AppImage independently and validates the exact helper bundle file set, modes, stage/protocol metadata and SHA-256 values;
4. launches the AppImage normally (without `APPIMAGE_EXTRACT_AND_RUN`), verifies the mounted helper payload as the desktop user, copies that exact payload through the production private-staging routine, and proves root can read the staged manifest and installer before any installed helper is removed;
5. removes the current helper and proves the AppImage performs an explicit missing-helper install with administrator authorization;
6. proves a byte-exact current helper is accepted without reinstalling or changing any helper file;
7. creates a safe incomplete/outdated state by removing only the installed helper manifest, then proves the AppImage requires an explicit update and restores an exact match;
8. verifies throughout that the test did not intentionally connect PIA or create a production Kill Switch firewall table.

A 15-minute VPN-first/firewall-reset safety timer is armed during the interactive AppImage portion. The test records and restores the user's original Kill Switch preference. On a failure after the helper was deliberately changed, the wrapper attempts to restore the current source-tree helper only if VPN and the production firewall table are both independently absent.

## AppImage FUSE privilege handoff

A normal AppImage mount may intentionally allow traversal only by the desktop user. Root therefore must not be assumed to read the FUSE mount directly. The production install/update path verifies the mounted payload, copies only the fixed helper bundle into a private `0700` directory on a normal filesystem, verifies the staged copy byte-for-byte, and passes only that staged fixed installer to `pkexec`. The privileged installer then performs its own manifest/hash validation before copying into `/usr/local/libexec/pia-bazzite`. The temporary staging directory is removed after the authorization/install attempt.

## Portable checksum correction

Stage 8B.2 also makes the generated `.sha256` sidecar contain only the AppImage basename. This avoids embedding the container-only `/workspace/...` path in local Podman builds and keeps the GitHub release checksum directly usable after download.

Stage 8C owns the broader release-candidate VPN/Kill-Switch regression. Stage 8B.2 is limited to proving the packaged installation boundary itself.
