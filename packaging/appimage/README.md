# AppImage packaging

`../build-appimage.sh` creates the x86_64 AppImage with PyInstaller and
appimagetool 1.9.1.

`../build-appimage-podman.sh` runs that build inside an Ubuntu 22.04
container and is the recommended local path on Bazzite.

The GitHub release workflow also uses Ubuntu 22.04. Building against that
older userspace avoids unnecessarily requiring the newest glibc while
remaining appropriate for supported Bazzite systems.

The AppImage bundles Python, PySide6, and the Python dependencies. It
deliberately uses the host for NetworkManager, WireGuard, D-Bus, the
Secret Service keyring, and desktop notifications.

## Session Kill Switch helper payload

The AppImage carries a fixed helper installation payload under
`usr/share/pia-bazzite/kill-switch-helper-bundle`. The payload contains only the
production helper/session launchers, their Python package, and the fixed installer,
plus a SHA-256 manifest generated during the build.

The privileged helper is never executed in place from the AppImage FUSE mount. Normal
AppImage mounts may deliberately be unreadable to root, so immediately before an explicit
install/update authorization the application copies the already verified payload into a
private normal-filesystem staging directory and verifies that staged copy again. Stage 8B
installs or upgrades that payload to the fixed root-owned
`/usr/local/libexec/pia-bazzite` boundary only after a visible confirmation and explicit
administrator authorization. The application compares every installed production helper
file with the SHA-256 payload from this exact AppImage before Kill Switch use. An older
helper is never accepted merely because its protocol/stage numbers look compatible.
Unsafe existing targets are not overwritten automatically.

## Release-integrity notes

`appimagetool` 1.9.1 is downloaded only when needed and is verified against a
pinned SHA-256 before it is made executable. The AppImage also contains
`BUILD_INFO.txt` with the build mode and source commit identifier.

The recommended local release build is:

```bash
PIA_BAZZITE_BUILD_MODE=release ./packaging/build-appimage-podman.sh
```

Release mode refuses a dirty/untracked Git tree and exports only `HEAD` through
`git archive`. Normal development/host tests continue to use the explicitly
labelled development staging mode so uncommitted test work can still be built.

The build collects a generated inventory and available upstream license files
for the complete installed Python runtime dependency graph, including
PySide6/Qt, below `usr/share/doc/pia-bazzite/third-party-python`. PySide6/Qt
open-source license texts are additionally bundled from pinned canonical copies
under `third-party-python/PySide6-Qt/`, so their presence does not depend on the
wheel exposing license files through package metadata.

Before a release candidate is frozen, run the non-privileged artifact inspection:

```bash
bash tools/release-stage8c2-packaging-host-test.sh
```

It builds a fresh development AppImage through the isolated Podman path, verifies
the SHA-256 sidecar, extracts the real artifact, and checks provenance, AppStream
metadata aliases, third-party inventory/license material, privacy markers, and the
current runtime version without installing the privileged helper.
