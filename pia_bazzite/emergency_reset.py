from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .kill_switch_client import KillSwitchClient, KillSwitchStatus
from .kill_switch_crash_state import CrashRecoveryStore
from .network_manager import ConnectionState


class EmergencyResetError(RuntimeError):
    """A deliberate last-resort release could not be proven safe."""


class VpnBackend(Protocol):
    def connection_state(self) -> ConnectionState:
        ...

    def disconnect(self, profile_uuid: str = "") -> None:
        ...


@dataclass(frozen=True, slots=True)
class EmergencyResetResult:
    vpn_was_connected: bool
    firewall_status: KillSwitchStatus


def run_verified_emergency_reset(
    *,
    client: KillSwitchClient,
    vpn_backend: VpnBackend,
    recovery_store: CrashRecoveryStore,
) -> EmergencyResetResult:
    """Release only after proving VPN-down, then verifying firewall absence.

    This is intentionally a last-resort path.  It never tries to reconnect and
    never removes the production firewall while NetworkManager still reports the
    fixed PIA WireGuard profile as active.  The privileged helper itself removes
    only the fixed PIA Bazzite table and returns a structurally verified disabled
    status before the unprivileged crash-recovery pathname may be discarded.
    """

    initial = vpn_backend.connection_state()
    if initial.connected:
        vpn_backend.disconnect(initial.uuid)

    verified = vpn_backend.connection_state()
    if verified.connected:
        raise EmergencyResetError(
            "Refusing Emergency Reset because the PIA VPN is still active after the disconnect request."
        )

    status = client.emergency_reset()
    if status.present or status.state != "disabled" or not status.verified:
        raise EmergencyResetError(
            "The installed helper did not verify that the production Kill Switch firewall is absent."
        )

    recovery_store.discard_untrusted_after_verified_release()
    return EmergencyResetResult(
        vpn_was_connected=initial.connected,
        firewall_status=status,
    )


__all__ = [
    "EmergencyResetError",
    "EmergencyResetResult",
    "VpnBackend",
    "run_verified_emergency_reset",
]
