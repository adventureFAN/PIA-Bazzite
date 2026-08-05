# Stage 4B.1 — Main-window polish

This small follow-up keeps Stage 4B fully simulated and changes no VPN,
NetworkManager, Polkit, helper, or nftables behavior.

## Adjustments

- Status title styling now uses `QFont` and `QPalette` instead of a label
  stylesheet, so the full tooltip keeps the normal system tooltip font and
  colors.
- Status title and compact summary sit closer together and align more naturally
  with the top of the shield.
- The public-IP refresh control is a smaller `QToolButton`.
- Fixed window widths are reduced from 790/840 px to 760/800 px.
- The Live Log wraps at the window width, disables the horizontal scrollbar,
  and keeps the action buttons clearly below the editor.

## Safety boundary

The preview still disables every real connection action. The update contains no
new privileged calls and does not import the kill-switch session client into the
main window.
