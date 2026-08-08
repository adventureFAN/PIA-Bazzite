from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .kill_switch_client import IPv6GuardStatus, KillSwitchStatus


class IPv6GuardLifecycleError(RuntimeError):
    """Base class for normal-VPN IPv6 guard lifecycle failures."""


class IPv6GuardStateError(IPv6GuardLifecycleError):
    """Raised when the helper reports a conflicting or unverified firewall state."""


class IPv6GuardConnectError(IPv6GuardLifecycleError):
    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        vpn_connected: bool | None = None,
        guard_status: IPv6GuardStatus | None = None,
        guard_retained: bool = True,
        cleanup_error: str = "",
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.vpn_connected = vpn_connected
        self.guard_status = guard_status
        self.guard_retained = bool(guard_retained)
        self.cleanup_error = cleanup_error.strip()


class IPv6GuardDisconnectError(IPv6GuardLifecycleError):
    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        vpn_disconnected: bool = False,
        guard_status: IPv6GuardStatus | None = None,
        guard_retained: bool = True,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.vpn_disconnected = bool(vpn_disconnected)
        self.guard_status = guard_status
        self.guard_retained = bool(guard_retained)


class IPv6GuardStartupError(IPv6GuardLifecycleError):
    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        vpn_connected: bool | None = None,
        guard_status: IPv6GuardStatus | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.vpn_connected = vpn_connected
        self.guard_status = guard_status


class GuardSession(Protocol):
    def open(self) -> object: ...
    def status(self) -> KillSwitchStatus: ...
    def ipv6_guard_status(self) -> IPv6GuardStatus: ...
    def ipv6_guard_enable(self) -> IPv6GuardStatus: ...
    def ipv6_guard_disable(self) -> IPv6GuardStatus: ...


class VpnBackend(Protocol):
    def connect(self, config_path: Path) -> str: ...
    def disconnect(self, profile_uuid: str = "") -> None: ...
    def is_connected(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class GuardedConnectResult:
    profile_uuid: str
    guard_status: IPv6GuardStatus


@dataclass(frozen=True, slots=True)
class GuardedDisconnectResult:
    guard_status: IPv6GuardStatus


@dataclass(frozen=True, slots=True)
class GuardStartupResult:
    disposition: str
    vpn_connected: bool
    guard_status: IPv6GuardStatus

    @property
    def adopted(self) -> bool:
        return self.disposition == "adopted-connected"


class IPv6GuardLifecycle:
    """Own the small IPv6-only guard used when the Session Kill Switch is off.

    The guard is intentionally distinct from the full fail-closed Kill Switch.
    It blocks only native IPv6 while an ordinary IPv4-only PIA WireGuard
    connection is considered active.  All transitions keep the guard in place
    until NetworkManager has been independently verified down.
    """

    def __init__(self, *, session: GuardSession, vpn_backend: VpnBackend) -> None:
        self.session = session
        self.vpn_backend = vpn_backend

    def connect(self, config_path: Path) -> GuardedConnectResult:
        self.session.open()
        self._require_full_kill_switch_absent()
        guard: IPv6GuardStatus | None = None
        try:
            # Arm and independently re-read the small firewall before
            # NetworkManager is allowed to create or activate the VPN.
            guard = self._ensure_guard_active()
            profile_uuid = str(self.vpn_backend.connect(config_path)).strip()
            if not profile_uuid:
                raise RuntimeError("NetworkManager returned no PIA profile UUID.")
            if not bool(self.vpn_backend.is_connected()):
                raise RuntimeError("NetworkManager did not report an active PIA VPN.")
            guard = self.session.ipv6_guard_status()
            self._require_guard_active(guard, action="post-connect status")
            return GuardedConnectResult(
                profile_uuid=profile_uuid,
                guard_status=guard,
            )
        except Exception as exc:
            vpn_connected = self._read_vpn_state_after_failure()
            guard_status = self._read_guard_status_after_failure(guard)
            cleanup_error = ""
            guard_retained = bool(guard_status and guard_status.present)
            # A failed normal connection may return ordinary IPv4, so release
            # the small IPv6 guard only after NetworkManager is independently
            # verified down.  Unknown/connected state always retains it.
            if vpn_connected is False and guard_status is not None and guard_status.present:
                try:
                    self._require_guard_active(guard_status, action="failed-connect cleanup preflight")
                    disabled = self.session.ipv6_guard_disable()
                    self._require_guard_disabled(disabled, action="failed-connect cleanup")
                    guard_status = disabled
                    guard_retained = False
                except Exception as cleanup_exc:
                    cleanup_error = str(cleanup_exc)
                    guard_retained = True
            elif vpn_connected is False and guard_status is not None:
                self._require_guard_disabled(guard_status, action="failed-connect cleanup preflight")
                guard_retained = False
            else:
                # If guard status itself became unreadable, fail safe and make
                # no removal attempt regardless of the NetworkManager result.
                guard_retained = True
            raise IPv6GuardConnectError(
                "Normal VPN connection failed while the IPv6 guard lifecycle was active.",
                cause=exc,
                vpn_connected=vpn_connected,
                guard_status=guard_status,
                guard_retained=guard_retained,
                cleanup_error=cleanup_error,
            ) from exc

    def disconnect(self, profile_uuid: str = "") -> GuardedDisconnectResult:
        self.session.open()
        self._require_full_kill_switch_absent()
        guard = self.session.ipv6_guard_status()
        if guard.present:
            self._require_guard_active(guard, action="disconnect preflight")
        try:
            self.vpn_backend.disconnect(profile_uuid)
            if bool(self.vpn_backend.is_connected()):
                raise RuntimeError("NetworkManager still reports the PIA VPN as active.")
        except Exception as exc:
            guard_status = self._read_guard_status_after_failure(guard)
            raise IPv6GuardDisconnectError(
                "The VPN could not be verified as disconnected; the IPv6 guard was retained.",
                cause=exc,
                vpn_disconnected=False,
                guard_status=guard_status,
                guard_retained=bool(guard_status.present),
            ) from exc

        try:
            disabled = self.session.ipv6_guard_disable()
            self._require_guard_disabled(disabled, action="intentional disconnect")
        except Exception as exc:
            guard_status = self._read_guard_status_after_failure(guard)
            raise IPv6GuardDisconnectError(
                "The VPN is disconnected, but the IPv6 guard could not be verified as released.",
                cause=exc,
                vpn_disconnected=True,
                guard_status=guard_status,
                guard_retained=True,
            ) from exc
        return GuardedDisconnectResult(guard_status=disabled)

    def release_after_verified_vpn_loss(self) -> GuardedDisconnectResult:
        """Release the small guard only after an unexpected VPN loss is verified."""

        self.session.open()
        self._require_full_kill_switch_absent()
        if bool(self.vpn_backend.is_connected()):
            raise IPv6GuardDisconnectError(
                "Refusing to release the IPv6 guard while the PIA VPN is still active.",
                vpn_disconnected=False,
                guard_status=self.session.ipv6_guard_status(),
                guard_retained=True,
            )
        guard = self.session.ipv6_guard_status()
        if guard.present:
            self._require_guard_active(guard, action="unexpected-loss release preflight")
        disabled = self.session.ipv6_guard_disable()
        self._require_guard_disabled(disabled, action="unexpected-loss release")
        return GuardedDisconnectResult(guard_status=disabled)

    def reconcile_startup(self) -> GuardStartupResult:
        """Adopt a crash-surviving guard or clean it only when the VPN is down."""

        self.session.open()
        self._require_full_kill_switch_absent()
        guard = self.session.ipv6_guard_status()
        vpn_connected = bool(self.vpn_backend.is_connected())

        if guard.present:
            self._require_guard_active(guard, action="startup status")
            if vpn_connected:
                return GuardStartupResult(
                    disposition="adopted-connected",
                    vpn_connected=True,
                    guard_status=guard,
                )
            disabled = self.session.ipv6_guard_disable()
            self._require_guard_disabled(disabled, action="stale startup cleanup")
            return GuardStartupResult(
                disposition="cleared-stale-guard",
                vpn_connected=False,
                guard_status=disabled,
            )

        self._require_guard_disabled(guard, action="startup status")
        if vpn_connected:
            try:
                self.vpn_backend.disconnect("")
                if bool(self.vpn_backend.is_connected()):
                    raise RuntimeError("PIA VPN remained active after startup safety disconnect.")
            except Exception as exc:
                raise IPv6GuardStartupError(
                    "PIA VPN is active without the required IPv6 guard and could not be stopped safely.",
                    cause=exc,
                    vpn_connected=True,
                    guard_status=guard,
                ) from exc
            return GuardStartupResult(
                disposition="stopped-unprotected-vpn",
                vpn_connected=False,
                guard_status=guard,
            )

        return GuardStartupResult(
            disposition="clean",
            vpn_connected=False,
            guard_status=guard,
        )

    def _ensure_guard_active(self) -> IPv6GuardStatus:
        status = self.session.ipv6_guard_status()
        if status.present:
            self._require_guard_active(status, action="connect preflight")
            return status
        self._require_guard_disabled(status, action="connect preflight")
        enabled = self.session.ipv6_guard_enable()
        self._require_guard_active(enabled, action="enable")
        verified = self.session.ipv6_guard_status()
        self._require_guard_active(verified, action="enable status")
        return verified

    def _require_full_kill_switch_absent(self) -> None:
        status = self.session.status()
        if (
            status.state != "disabled"
            or status.present
            or not status.verified
            or status.problems
        ):
            raise IPv6GuardStateError(
                "The full Session Kill Switch is present or unverified; the small IPv6 guard "
                "will not operate alongside it."
            )

    @staticmethod
    def _require_guard_active(status: IPv6GuardStatus, *, action: str) -> None:
        if not isinstance(status, IPv6GuardStatus) or not status.protection_active:
            raise IPv6GuardStateError(
                f"IPv6 guard {action} did not return verified active protection."
            )

    @staticmethod
    def _require_guard_disabled(status: IPv6GuardStatus, *, action: str) -> None:
        if not isinstance(status, IPv6GuardStatus):
            raise IPv6GuardStateError(
                f"IPv6 guard {action} returned an unexpected object."
            )
        if status.state != "disabled" or status.present or not status.verified or status.problems:
            raise IPv6GuardStateError(
                f"IPv6 guard {action} did not return a verified disabled state."
            )

    def _read_vpn_state_after_failure(self) -> bool | None:
        try:
            return bool(self.vpn_backend.is_connected())
        except Exception:
            return None

    def _read_guard_status_after_failure(
        self,
        fallback: IPv6GuardStatus | None,
    ) -> IPv6GuardStatus | None:
        try:
            return self.session.ipv6_guard_status()
        except Exception:
            return fallback


__all__ = [
    "GuardStartupResult",
    "GuardedConnectResult",
    "GuardedDisconnectResult",
    "IPv6GuardConnectError",
    "IPv6GuardDisconnectError",
    "IPv6GuardLifecycle",
    "IPv6GuardLifecycleError",
    "IPv6GuardStartupError",
    "IPv6GuardStateError",
]
