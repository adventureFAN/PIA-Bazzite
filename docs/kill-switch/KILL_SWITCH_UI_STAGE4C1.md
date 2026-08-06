# Kill Switch Runtime UI Polish — Stage 4C.1

Stage 4C.1 applies visual and wording feedback to the optional runtime-state preview without adding privileged or network behavior.

## Wording

- **VPN ready** identifies the disconnected state with the kill switch disabled.
- **VPN & kill switch ready** identifies the intentionally disconnected state where the optional feature will be applied before the next connection.
- **Protection error** includes a visible instruction to open the Live Log.
- Every full status tooltip contains deliberate line breaks so it remains readable on ordinary displays.

## Layout

- The status title and summary are moved four pixels lower as one block.
- The Live Log action buttons receive a larger top margin and remain visually separate from the text area.
- The fixed main-window sizes are reduced to 740 × 510 without the Live Log and 760 × 780 with it.

## Safety

This stage changes only presentation, translations, previews, tests, and documentation. It does not use Polkit, NetworkManager, nftables, or the installed helper.
