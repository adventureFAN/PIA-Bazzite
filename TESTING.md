# PIA Bazzite 0.5.0 release test checklist

The static self-test does not contact PIA and does not change NetworkManager.

1. Run `./self_test.py`; all checks must pass.
2. Start from source and confirm `./run.sh --version` is not required for GUI use.
3. Confirm the window title is only `PIA Bazzite`.
4. Confirm the green PIA shield is the application/window icon.
5. Confirm English is the default and German can be selected.
6. Test System, Light, and Dark appearance.
7. Confirm the compact and live-log window sizes are locked as designed.
8. Connect from the main window and verify public IP, country, DNS, and IPv6 status.
9. Confirm the tray icon is red while disconnected and green while connected.
10. Left-click the tray icon; the existing main window must be shown.
11. Right-click the tray icon; the native menu must remain open normally.
12. Use the tray to disconnect, reconnect, and switch locations.
13. Test fastest location and the ten quick locations.
14. Confirm the disabled tray status row contains one colored dot only.
15. Test all documented keyboard shortcuts.
16. Test the live log copy, clear, and save actions.
17. Confirm a second application start raises the existing instance.
18. On Bazzite, build with `./packaging/build-appimage-podman.sh`.
19. Run `APPIMAGE_EXTRACT_AND_RUN=1 ./PIA-Bazzite-0.5.0-x86_64.AppImage --version`.
20. Integrate the AppImage with Gear Lever and repeat the connection tests.
