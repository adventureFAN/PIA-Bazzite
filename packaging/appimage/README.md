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
