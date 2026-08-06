from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class KillSwitchMode(str, Enum):
    """User-visible optional session kill-switch states."""

    READY = "ready"
    ARMED = "armed"
    VPN_ONLY = "vpn_only"
    ACTIVE = "active"
    BLOCKING = "blocking"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class KillSwitchObservation:
    """Immutable input used to derive one trustworthy UI state.

    ``feature_enabled`` is deliberately explicit. A connected VPN without a
    firewall table is normal when the optional kill switch is disabled, but it
    is a protection error when the user enabled the feature.
    """

    feature_enabled: bool
    vpn_connected: bool
    table_present: bool
    table_verified: bool
    problems: tuple[str, ...] = ()
    error: str = ""

    @classmethod
    def create(
        cls,
        *,
        vpn_connected: bool,
        table_present: bool,
        table_verified: bool,
        feature_enabled: bool = True,
        problems: Iterable[str] = (),
        error: str = "",
    ) -> "KillSwitchObservation":
        normalized_problems = tuple(
            item.strip() for item in problems if item and item.strip()
        )
        return cls(
            feature_enabled=bool(feature_enabled),
            vpn_connected=bool(vpn_connected),
            table_present=bool(table_present),
            table_verified=bool(table_verified),
            problems=normalized_problems,
            error=error.strip(),
        )


@dataclass(frozen=True, slots=True)
class KillSwitchViewState:
    mode: KillSwitchMode
    title_key: str
    summary_key: str
    detail_key: str
    tray_status_key: str
    tray_tooltip_key: str
    log_key: str
    log_level: str
    icon_state: str
    feature_enabled: bool
    firewall_active: bool
    protection_guaranteed: bool
    diagnostic: str = ""

    @property
    def is_error(self) -> bool:
        return self.mode is KillSwitchMode.ERROR

    @property
    def is_blocking(self) -> bool:
        return self.mode is KillSwitchMode.BLOCKING


_STATE_METADATA: dict[KillSwitchMode, dict[str, object]] = {
    KillSwitchMode.READY: {
        "title_key": "kill_switch.state.ready",
        "summary_key": "kill_switch.summary.ready",
        "detail_key": "kill_switch.detail.ready",
        "tray_status_key": "tray.kill_switch_status.ready",
        "tray_tooltip_key": "tray.kill_switch_tooltip.ready",
        "log_key": "log.kill_switch.ready",
        "log_level": "info",
        "icon_state": "ready",
        "firewall_active": False,
        "protection_guaranteed": False,
    },
    KillSwitchMode.ARMED: {
        "title_key": "kill_switch.state.armed",
        "summary_key": "kill_switch.summary.armed",
        "detail_key": "kill_switch.detail.armed",
        "tray_status_key": "tray.kill_switch_status.armed",
        "tray_tooltip_key": "tray.kill_switch_tooltip.armed",
        "log_key": "log.kill_switch.armed",
        "log_level": "info",
        "icon_state": "armed",
        "firewall_active": False,
        "protection_guaranteed": False,
    },
    KillSwitchMode.VPN_ONLY: {
        "title_key": "kill_switch.state.vpn_only",
        "summary_key": "kill_switch.summary.vpn_only",
        "detail_key": "kill_switch.detail.vpn_only",
        "tray_status_key": "tray.kill_switch_status.vpn_only",
        "tray_tooltip_key": "tray.kill_switch_tooltip.vpn_only",
        "log_key": "log.kill_switch.vpn_only",
        "log_level": "ok",
        "icon_state": "vpn_only",
        "firewall_active": False,
        "protection_guaranteed": False,
    },
    KillSwitchMode.ACTIVE: {
        "title_key": "kill_switch.state.active",
        "summary_key": "kill_switch.summary.active",
        "detail_key": "kill_switch.detail.active",
        "tray_status_key": "tray.kill_switch_status.active",
        "tray_tooltip_key": "tray.kill_switch_tooltip.active",
        "log_key": "log.kill_switch.active",
        "log_level": "ok",
        "icon_state": "active",
        "firewall_active": True,
        "protection_guaranteed": True,
    },
    KillSwitchMode.BLOCKING: {
        "title_key": "kill_switch.state.blocking",
        "summary_key": "kill_switch.summary.blocking",
        "detail_key": "kill_switch.detail.blocking",
        "tray_status_key": "tray.kill_switch_status.blocking",
        "tray_tooltip_key": "tray.kill_switch_tooltip.blocking",
        "log_key": "log.kill_switch.blocking",
        "log_level": "warning",
        "icon_state": "blocking",
        "firewall_active": True,
        "protection_guaranteed": True,
    },
    KillSwitchMode.ERROR: {
        "title_key": "kill_switch.state.error",
        "summary_key": "kill_switch.summary.error",
        "detail_key": "kill_switch.detail.error",
        "tray_status_key": "tray.kill_switch_status.error",
        "tray_tooltip_key": "tray.kill_switch_tooltip.error",
        "log_key": "log.kill_switch.error",
        "log_level": "error",
        "icon_state": "error",
        "firewall_active": False,
        "protection_guaranteed": False,
    },
}


def derive_kill_switch_view_state(
    observation: KillSwitchObservation,
) -> KillSwitchViewState:
    """Derive a conservative state while respecting optional operation."""

    diagnostic = observation.error
    if not diagnostic and observation.problems:
        diagnostic = "; ".join(observation.problems)

    if diagnostic:
        mode = KillSwitchMode.ERROR
    elif not observation.feature_enabled:
        if observation.table_present:
            mode = KillSwitchMode.ERROR
            diagnostic = (
                "The kill-switch table is present although the feature is disabled."
            )
        elif observation.vpn_connected:
            mode = KillSwitchMode.VPN_ONLY
        else:
            mode = KillSwitchMode.READY
    elif observation.table_present and not observation.table_verified:
        mode = KillSwitchMode.ERROR
        diagnostic = "The kill-switch table is present but not verified."
    elif observation.table_present and observation.table_verified:
        mode = (
            KillSwitchMode.ACTIVE
            if observation.vpn_connected
            else KillSwitchMode.BLOCKING
        )
    elif observation.vpn_connected:
        mode = KillSwitchMode.ERROR
        diagnostic = "The VPN is connected without a verified kill-switch table."
    else:
        mode = KillSwitchMode.ARMED

    metadata = _STATE_METADATA[mode]
    return KillSwitchViewState(
        mode=mode,
        title_key=str(metadata["title_key"]),
        summary_key=str(metadata["summary_key"]),
        detail_key=str(metadata["detail_key"]),
        tray_status_key=str(metadata["tray_status_key"]),
        tray_tooltip_key=str(metadata["tray_tooltip_key"]),
        log_key=str(metadata["log_key"]),
        log_level=str(metadata["log_level"]),
        icon_state=str(metadata["icon_state"]),
        feature_enabled=observation.feature_enabled,
        firewall_active=bool(metadata["firewall_active"]),
        protection_guaranteed=bool(metadata["protection_guaranteed"]),
        diagnostic=diagnostic,
    )


def sample_kill_switch_states() -> tuple[KillSwitchViewState, ...]:
    """Return deterministic states for safe stage-4 previews."""

    return (
        derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=False,
                vpn_connected=False,
                table_present=False,
                table_verified=False,
            )
        ),
        derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=False,
                table_present=False,
                table_verified=True,
            )
        ),
        derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=False,
                vpn_connected=True,
                table_present=False,
                table_verified=False,
            )
        ),
        derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=True,
                table_present=True,
                table_verified=True,
            )
        ),
        derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=False,
                table_present=True,
                table_verified=True,
            )
        ),
        derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=True,
                table_present=False,
                table_verified=False,
                error="Protection could not be verified.",
            )
        ),
    )


def status_color_hex(state: str, *, dark_mode: bool) -> str:
    """Return the shared tray/shield color for one normalized state."""

    aliases = {
        "connected": "active",
        "disconnected": "ready",
        "busy": "blocking",
        "application": "application",
    }
    normalized = aliases.get(state, state)
    if normalized == "ready":
        return "#b0bec5" if dark_mode else "#546e7a"
    if normalized == "armed":
        return "#cfd8dc" if dark_mode else "#78909c"
    if normalized == "vpn_only":
        return "#64b5f6" if dark_mode else "#1565c0"
    return {
        "active": "#2e7d32",
        "blocking": "#ef6c00",
        "error": "#c62828",
        "application": "#2e7d32",
    }.get(normalized, "#2e7d32")


__all__ = [
    "KillSwitchMode",
    "KillSwitchObservation",
    "KillSwitchViewState",
    "derive_kill_switch_view_state",
    "sample_kill_switch_states",
    "status_color_hex",
]
