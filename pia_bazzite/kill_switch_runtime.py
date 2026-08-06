from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .kill_switch_client import KillSwitchClientError, KillSwitchStatus
from .kill_switch_state import (
    KillSwitchObservation,
    KillSwitchViewState,
    derive_kill_switch_view_state,
)


KILL_SWITCH_ENABLED_KEY = "kill_switch/enabled"


class SettingsLike(Protocol):
    def value(self, key: str, default: Any = None, *, type: type | None = None) -> Any:
        ...

    def setValue(self, key: str, value: Any) -> None:
        ...

    def sync(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class KillSwitchRuntimeSnapshot:
    feature_enabled: bool
    vpn_connected: bool
    helper_status: KillSwitchStatus | None = None
    error: str = ""

    def to_view_state(self) -> KillSwitchViewState:
        status = self.helper_status
        return derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=self.feature_enabled,
                vpn_connected=self.vpn_connected,
                table_present=False if status is None else status.present,
                table_verified=False if status is None else status.verified,
                problems=() if status is None else status.problems,
                error=self.error,
            )
        )


class KillSwitchRuntimeController:
    """Read-only bridge between optional settings, VPN state, and helper status.

    Stage 4C deliberately does not install, enable, disable, or modify firewall
    rules. When the feature is disabled the helper is not contacted at all.
    When enabled, callers may inject an already-authorized session ``status``
    method. This keeps GUI rendering separate from privileged lifecycle work.
    """

    def __init__(
        self,
        settings: SettingsLike,
        *,
        status_reader: Callable[[], KillSwitchStatus] | None = None,
    ) -> None:
        self.settings = settings
        self.status_reader = status_reader

    @property
    def feature_enabled(self) -> bool:
        return bool(
            self.settings.value(
                KILL_SWITCH_ENABLED_KEY,
                False,
                type=bool,
            )
        )

    def set_feature_enabled(self, enabled: bool) -> None:
        self.settings.setValue(KILL_SWITCH_ENABLED_KEY, bool(enabled))
        self.settings.sync()

    def snapshot(self, *, vpn_connected: bool) -> KillSwitchRuntimeSnapshot:
        enabled = self.feature_enabled
        if not enabled:
            return KillSwitchRuntimeSnapshot(
                feature_enabled=False,
                vpn_connected=bool(vpn_connected),
            )

        if self.status_reader is None:
            return KillSwitchRuntimeSnapshot(
                feature_enabled=True,
                vpn_connected=bool(vpn_connected),
                error=(
                    "Kill-switch status is unavailable because no authorized "
                    "helper session is open."
                ),
            )

        try:
            status = self.status_reader()
        except KillSwitchClientError as exc:
            return KillSwitchRuntimeSnapshot(
                feature_enabled=True,
                vpn_connected=bool(vpn_connected),
                error=str(exc).strip() or exc.__class__.__name__,
            )
        except Exception as exc:  # defensive GUI boundary; never claim protection
            return KillSwitchRuntimeSnapshot(
                feature_enabled=True,
                vpn_connected=bool(vpn_connected),
                error=f"Unexpected kill-switch status failure: {exc}",
            )

        return KillSwitchRuntimeSnapshot(
            feature_enabled=True,
            vpn_connected=bool(vpn_connected),
            helper_status=status,
        )

    def view_state(self, *, vpn_connected: bool) -> KillSwitchViewState:
        return self.snapshot(vpn_connected=vpn_connected).to_view_state()


__all__ = [
    "KILL_SWITCH_ENABLED_KEY",
    "KillSwitchRuntimeController",
    "KillSwitchRuntimeSnapshot",
    "SettingsLike",
]
