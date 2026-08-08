# Stage 8B — packaged helper installation and upgrade gate

Stage 8B turns the helper payload introduced by Stage 8A into an explicit AppImage
installation/upgrade flow. It does not weaken the fixed root-owned execution boundary.

## Release invariants

- Source-tree development runs keep the established manual helper workflow.
- The AppImage `AppRun` exports one fixed path to its read-only helper bundle.
- Before the Session Kill Switch can be enabled or crash-recovery startup can trust a
  helper, the AppImage compares every installed production helper byte against the
  SHA-256 payload carried by that exact AppImage.
- Matching protocol/stage numbers alone are not sufficient to accept an older helper.
- Missing or safely replaceable outdated installations require a visible confirmation
  and a separate Polkit administrator authorization.
- Unsafe targets (symlinks, wrong ownership, wrong modes, hard links, unsafe directories)
  are never overwritten automatically.
- The privileged installer revalidates the AppImage bundle manifest and source hashes
  immediately before copying files to `/usr/local/libexec/pia-bazzite`.
- Installation/upgrade changes helper files only. It does not start/stop VPN, add/remove
  nftables rules, or alter a crash-recovery record.
- After installer success the GUI independently re-audits the complete root-owned
  boundary. Kill Switch operation continues only after an exact match.
- AppImage-only bundle path variables are stripped before normal privileged helper
  sessions so the installed helper never consumes a user-writable runtime path.

The real Stage-8B host gate is intentionally separate. It builds the 0.6.0 release
candidate, runs it through the AppImage execution path, and proves missing/current/
outdated helper behavior on the host before Stage 8C release regression.


## Stage 8B.1 self-test harness correction

The Stage-8B production gate deliberately rejects a `pkexec` or `bash` executable that is not a root-owned, non-writable regular file. The first unprivileged self-test accidentally used a user-owned executable in a temporary directory as a fake `pkexec`, so the production security check correctly rejected the test fixture before the fake runner could be exercised.

Stage 8B.1 fixes only the test harness: install-flow tests mock the executable-boundary check while testing argument construction and authorization-result handling, and a separate negative regression test now proves that a user-owned fake `pkexec` is rejected before the runner is called. The production verification in `pia_bazzite/helper_installation.py` is unchanged.

## Stage 8B.2 real AppImage host gate

Stage 8B.2 validates this design through the actual 0.6.0 AppImage path. Because normal AppImage FUSE mounts may intentionally deny traversal to root, the application copies the already verified helper payload into a private normal-filesystem staging directory immediately before privilege handoff and verifies the staged copy again. The host gate proves that exact staging path is root-readable before changing the installed helper, then exercises missing, exact-current, and safe-outdated helper states. See `STAGE8B2_REAL_APPIMAGE_HELPER_HOST_GATE.md`.
