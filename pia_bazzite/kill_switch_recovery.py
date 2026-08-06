from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any, Protocol
import uuid

from .kill_switch_client import KillSwitchStatus
from .kill_switch_connection import (
    ConnectionPlan,
    UnsafeConnectionPlanError,
    normalize_wireguard_endpoint,
    read_wireguard_endpoint,
)


MAX_PHYSICAL_INTERFACES = 8
MAX_ENDPOINTS = 32
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
VPN_INTERFACE_NAME = "piabazzite"


class RecoveryOrchestrationError(RuntimeError):
    """Base error for fail-closed tunnel recovery and server switching."""


class UnsafeRecoveryPlanError(RecoveryOrchestrationError):
    """A reconnect or server-switch input is not safe enough to execute."""


class ProtectedReconnectError(RecoveryOrchestrationError):
    """A protected reconnect failed while the firewall lock was retained."""

    def __init__(
        self,
        message: str,
        *,
        firewall_retained: bool = True,
        rollback_error: str = "",
    ) -> None:
        super().__init__(message)
        self.firewall_retained = bool(firewall_retained)
        self.rollback_error = rollback_error


class ProtectedServerSwitchError(RecoveryOrchestrationError):
    """A protected server switch failed without deliberately opening traffic."""

    def __init__(
        self,
        message: str,
        *,
        old_vpn_disconnected: bool,
        firewall_retained: bool = True,
        rollback_error: str = "",
    ) -> None:
        super().__init__(message)
        self.old_vpn_disconnected = bool(old_vpn_disconnected)
        self.firewall_retained = bool(firewall_retained)
        self.rollback_error = rollback_error


class RecoveryPhase(str, Enum):
    RECONNECT_PREFLIGHT_STARTED = "reconnect-preflight-started"
    RECONNECT_PREFLIGHT_VERIFIED = "reconnect-preflight-verified"
    SWITCH_PREFLIGHT_STARTED = "switch-preflight-started"
    SWITCH_PREFLIGHT_VERIFIED = "switch-preflight-verified"
    OLD_VPN_STOPPING = "old-vpn-stopping"
    OLD_VPN_STOPPED = "old-vpn-stopped"
    BLOCKED_PATH_CHECK_STARTED = "blocked-path-check-started"
    BLOCKED_PATH_VERIFIED = "blocked-path-verified"
    NEW_ROUTE_RESOLVING = "new-route-resolving"
    NEW_ROUTE_RESOLVED = "new-route-resolved"
    FIREWALL_RETARGET_STARTED = "firewall-retarget-started"
    FIREWALL_RETARGETED = "firewall-retargeted"
    VPN_RECONNECTING = "vpn-reconnecting"
    VPN_RECONNECTED = "vpn-reconnected"
    NEW_VPN_STARTING = "new-vpn-starting"
    NEW_VPN_STARTED = "new-vpn-started"
    POSTCHECK_STARTED = "postcheck-started"
    RECONNECT_VERIFIED = "reconnect-verified"
    SWITCH_VERIFIED = "switch-verified"
    ROLLBACK_STARTED = "rollback-started"
    ROLLBACK_COMPLETED = "rollback-completed"


@dataclass(frozen=True, slots=True)
class RecoveryEvent:
    phase: RecoveryPhase
    level: str
    message: str


@dataclass(frozen=True, slots=True)
class FirewallRoutePlan:
    """Strict endpoint and physical-interface allowlist for one VPN route."""

    physical_interfaces: tuple[str, ...]
    endpoints: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        physical_interfaces: Iterable[str],
        endpoints: Iterable[str],
    ) -> "FirewallRoutePlan":
        return cls(
            physical_interfaces=_normalize_interfaces(physical_interfaces),
            endpoints=_normalize_endpoints(endpoints),
        )

    @classmethod
    def from_connection_plan(cls, plan: ConnectionPlan) -> "FirewallRoutePlan":
        if not isinstance(plan, ConnectionPlan):
            raise UnsafeRecoveryPlanError("Expected a validated connection plan.")
        return cls.create(
            physical_interfaces=plan.physical_interfaces,
            endpoints=plan.endpoints,
        )


@dataclass(frozen=True, slots=True)
class PreparedServerSwitch:
    """A private new WireGuard config prepared through the still-active old VPN."""

    config_path: Path
    endpoint: str

    @classmethod
    def create(cls, *, config_path: Path) -> "PreparedServerSwitch":
        path = Path(config_path)
        try:
            endpoint = read_wireguard_endpoint(path)
        except UnsafeConnectionPlanError as exc:
            raise UnsafeRecoveryPlanError(str(exc)) from exc
        return cls(config_path=path, endpoint=endpoint)

    def verify(self) -> None:
        try:
            actual = read_wireguard_endpoint(self.config_path)
        except UnsafeConnectionPlanError as exc:
            raise UnsafeRecoveryPlanError(str(exc)) from exc
        if actual != self.endpoint:
            raise UnsafeRecoveryPlanError(
                "Prepared server-switch configuration changed after validation."
            )

    def build_connection_plan(self, *, physical_interface: str) -> ConnectionPlan:
        self.verify()
        try:
            plan = ConnectionPlan.create(
                config_path=self.config_path,
                physical_interfaces=(physical_interface,),
                endpoints=(self.endpoint,),
            )
            plan.verify_config_file()
        except UnsafeConnectionPlanError as exc:
            raise UnsafeRecoveryPlanError(str(exc)) from exc
        return plan


@dataclass(frozen=True, slots=True)
class ProtectedReconnectResult:
    profile_uuid: str
    firewall_status: KillSwitchStatus
    route_plan: FirewallRoutePlan


@dataclass(frozen=True, slots=True)
class ProtectedServerSwitchResult:
    profile_uuid: str
    firewall_status: KillSwitchStatus
    previous_route_plan: FirewallRoutePlan
    connection_plan: ConnectionPlan


class RecoverySessionLike(Protocol):
    def open(self) -> Any:
        ...

    def status(self) -> KillSwitchStatus:
        ...

    def set_interfaces(self, interfaces: Sequence[str]) -> KillSwitchStatus:
        ...

    def set_endpoints(self, endpoints: Sequence[str]) -> KillSwitchStatus:
        ...


class RecoveryVpnBackend(Protocol):
    def connect(self, config_path: Path) -> str:
        ...

    def reconnect(self, profile_uuid: str) -> str:
        ...

    def is_connected(self) -> bool:
        ...

    def disconnect(self, profile_uuid: str = "") -> None:
        ...


class KillSwitchRecoveryOrchestrator:
    """Reconnect or switch servers without ever deliberately removing the lock.

    The caller prepares PIA API data and private configuration files. This small
    boundary only performs deterministic safety ordering. Any failure leaves the
    production firewall table in place and never calls ``disable``.
    """

    def __init__(
        self,
        *,
        session: RecoverySessionLike,
        vpn_backend: RecoveryVpnBackend,
        event_sink: Callable[[RecoveryEvent], None] | None = None,
    ) -> None:
        self.session = session
        self.vpn_backend = vpn_backend
        self.event_sink = event_sink

    def reconnect(
        self,
        *,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
        blocked_path_probe: Callable[[], bool],
    ) -> ProtectedReconnectResult:
        profile = _normalize_profile_uuid(profile_uuid)
        route = _require_route_plan(route_plan)

        self._emit(
            RecoveryPhase.RECONNECT_PREFLIGHT_STARTED,
            "info",
            "The retained firewall lock and disconnected VPN are being verified.",
        )
        self._open_and_verify_lock(error_type="reconnect")
        try:
            if self.vpn_backend.is_connected():
                raise ProtectedReconnectError(
                    "Protected reconnect was refused because NetworkManager still reports an active VPN."
                )
        except ProtectedReconnectError:
            raise
        except Exception as exc:
            raise ProtectedReconnectError(
                f"VPN state could not be verified before reconnect: {exc}"
            ) from exc
        self._emit(
            RecoveryPhase.RECONNECT_PREFLIGHT_VERIFIED,
            "ok",
            "The VPN is down and the verified firewall lock remains active.",
        )

        self._prove_blocked_path(blocked_path_probe, operation="reconnect")
        self._retarget_firewall(route, previous=None, operation="reconnect")

        self._emit(
            RecoveryPhase.VPN_RECONNECTING,
            "info",
            "NetworkManager is reactivating the existing WireGuard profile under protection.",
        )
        returned_profile = ""
        try:
            returned_profile = _normalize_profile_uuid(
                self.vpn_backend.reconnect(profile)
            )
            if returned_profile != profile:
                raise UnsafeRecoveryPlanError(
                    "NetworkManager returned a different profile UUID during reconnect."
                )
        except Exception as exc:
            rollback_error = self._disconnect_if_active(returned_profile or profile)
            raise ProtectedReconnectError(
                f"Protected reconnect failed while the firewall lock remained active: {exc}",
                rollback_error=rollback_error,
            ) from exc
        self._emit(
            RecoveryPhase.VPN_RECONNECTED,
            "info",
            "NetworkManager returned from the protected reconnect request.",
        )

        status = self._verify_postconnect(
            profile_uuid=profile,
            operation="reconnect",
            switch=False,
        )
        self._emit(
            RecoveryPhase.RECONNECT_VERIFIED,
            "ok",
            "The reconnected VPN and retained firewall lock are verified.",
        )
        return ProtectedReconnectResult(
            profile_uuid=profile,
            firewall_status=status,
            route_plan=route,
        )

    def switch_server(
        self,
        *,
        current_profile_uuid: str,
        current_route_plan: FirewallRoutePlan,
        candidate: PreparedServerSwitch,
        blocked_path_probe: Callable[[], bool],
        physical_interface_resolver: Callable[[str], str],
    ) -> ProtectedServerSwitchResult:
        current_profile = _normalize_profile_uuid(current_profile_uuid)
        current_route = _require_route_plan(current_route_plan)
        if not isinstance(candidate, PreparedServerSwitch):
            raise UnsafeRecoveryPlanError("Expected a prepared server-switch candidate.")
        candidate.verify()
        if candidate.endpoint in current_route.endpoints:
            raise ProtectedServerSwitchError(
                "Protected server switch was refused because the new endpoint is unchanged.",
                old_vpn_disconnected=False,
            )

        self._emit(
            RecoveryPhase.SWITCH_PREFLIGHT_STARTED,
            "info",
            "The current VPN, new configuration, and active firewall lock are being verified.",
        )
        self._open_and_verify_lock(error_type="switch")
        try:
            connected = bool(self.vpn_backend.is_connected())
        except Exception as exc:
            raise ProtectedServerSwitchError(
                f"VPN state could not be verified before the server switch: {exc}",
                old_vpn_disconnected=False,
            ) from exc
        if not connected:
            raise ProtectedServerSwitchError(
                "Protected server switch requires the old VPN to still be connected.",
                old_vpn_disconnected=False,
            )
        self._emit(
            RecoveryPhase.SWITCH_PREFLIGHT_VERIFIED,
            "ok",
            "The old VPN and firewall lock are verified before the transition.",
        )

        self._emit(
            RecoveryPhase.OLD_VPN_STOPPING,
            "info",
            "The old WireGuard profile is being stopped while the lock remains active.",
        )
        try:
            self.vpn_backend.disconnect(current_profile)
            if self.vpn_backend.is_connected():
                raise RuntimeError(
                    "NetworkManager still reports the old VPN as connected."
                )
        except Exception as exc:
            raise ProtectedServerSwitchError(
                f"The old VPN could not be stopped safely: {exc}",
                old_vpn_disconnected=False,
            ) from exc
        self._emit(
            RecoveryPhase.OLD_VPN_STOPPED,
            "ok",
            "The old VPN is down and the firewall lock was not relaxed.",
        )

        try:
            self._prove_blocked_path(blocked_path_probe, operation="switch")

            self._emit(
                RecoveryPhase.NEW_ROUTE_RESOLVING,
                "info",
                "The physical route to the new numeric endpoint is being resolved while traffic is blocked.",
            )
            physical_interface = physical_interface_resolver(candidate.endpoint)
            new_plan = candidate.build_connection_plan(
                physical_interface=physical_interface
            )
            self._emit(
                RecoveryPhase.NEW_ROUTE_RESOLVED,
                "ok",
                "The new endpoint and physical route are validated.",
            )

            new_route = FirewallRoutePlan.from_connection_plan(new_plan)
            self._retarget_firewall(
                new_route,
                previous=current_route,
                operation="switch",
            )
        except ProtectedServerSwitchError:
            raise
        except Exception as exc:
            raise ProtectedServerSwitchError(
                f"The new protected route could not be prepared: {exc}",
                old_vpn_disconnected=True,
            ) from exc

        self._emit(
            RecoveryPhase.NEW_VPN_STARTING,
            "info",
            "NetworkManager may start the new WireGuard profile now.",
        )
        new_profile = ""
        try:
            raw_profile = str(self.vpn_backend.connect(new_plan.config_path)).strip()
            new_profile = _normalize_profile_uuid(raw_profile)
        except Exception as exc:
            rollback_error = self._disconnect_if_active(new_profile)
            raise ProtectedServerSwitchError(
                f"The new VPN could not be started; the firewall lock remains active: {exc}",
                old_vpn_disconnected=True,
                rollback_error=rollback_error,
            ) from exc
        self._emit(
            RecoveryPhase.NEW_VPN_STARTED,
            "info",
            "NetworkManager returned from the protected server-switch start request.",
        )

        status = self._verify_postconnect(
            profile_uuid=new_profile,
            operation="switch",
            switch=True,
        )
        self._emit(
            RecoveryPhase.SWITCH_VERIFIED,
            "ok",
            "The new VPN and exact replacement firewall route are verified.",
        )
        return ProtectedServerSwitchResult(
            profile_uuid=new_profile,
            firewall_status=status,
            previous_route_plan=current_route,
            connection_plan=new_plan,
        )

    def _open_and_verify_lock(self, *, error_type: str) -> KillSwitchStatus:
        try:
            self.session.open()
            status = self.session.status()
            _require_active_status(status, action=f"{error_type} preflight")
            return status
        except Exception as exc:
            if error_type == "switch":
                raise ProtectedServerSwitchError(
                    f"The active firewall lock could not be verified before the server switch: {exc}",
                    old_vpn_disconnected=False,
                ) from exc
            raise ProtectedReconnectError(
                f"The active firewall lock could not be verified before reconnect: {exc}"
            ) from exc

    def _prove_blocked_path(
        self,
        probe: Callable[[], bool],
        *,
        operation: str,
    ) -> None:
        if not callable(probe):
            message = "A blocked-path proof is required before protected recovery."
            if operation == "switch":
                raise ProtectedServerSwitchError(
                    message,
                    old_vpn_disconnected=True,
                )
            raise ProtectedReconnectError(message)
        self._emit(
            RecoveryPhase.BLOCKED_PATH_CHECK_STARTED,
            "info",
            "The ordinary network path is being tested while the firewall lock remains active.",
        )
        try:
            blocked = bool(probe())
        except Exception as exc:
            message = f"The blocked-path probe failed; the firewall lock remains active: {exc}"
            if operation == "switch":
                raise ProtectedServerSwitchError(
                    message,
                    old_vpn_disconnected=True,
                ) from exc
            raise ProtectedReconnectError(message) from exc
        if not blocked:
            message = "The ordinary path was not proven blocked; protected recovery was stopped."
            if operation == "switch":
                raise ProtectedServerSwitchError(
                    message,
                    old_vpn_disconnected=True,
                )
            raise ProtectedReconnectError(message)
        self._emit(
            RecoveryPhase.BLOCKED_PATH_VERIFIED,
            "ok",
            "Every previously reachable ordinary path is blocked.",
        )

    def _retarget_firewall(
        self,
        target: FirewallRoutePlan,
        *,
        previous: FirewallRoutePlan | None,
        operation: str,
    ) -> KillSwitchStatus:
        self._emit(
            RecoveryPhase.FIREWALL_RETARGET_STARTED,
            "info",
            "The verified firewall allowlists are being updated without removing the lock.",
        )
        try:
            if previous is None:
                status = self.session.set_interfaces(target.physical_interfaces)
                _require_active_status(status, action="set reconnect interfaces")
                status = self.session.set_endpoints(target.endpoints)
                _require_active_status(status, action="set reconnect endpoints")
            else:
                union_interfaces = tuple(
                    sorted(set(previous.physical_interfaces) | set(target.physical_interfaces))
                )
                union_endpoints = tuple(
                    sorted(set(previous.endpoints) | set(target.endpoints))
                )
                status = self.session.set_interfaces(union_interfaces)
                _require_active_status(status, action="extend switch interfaces")
                status = self.session.set_endpoints(union_endpoints)
                _require_active_status(status, action="extend switch endpoints")
                status = self.session.set_endpoints(target.endpoints)
                _require_active_status(status, action="retire old switch endpoints")
                status = self.session.set_interfaces(target.physical_interfaces)
                _require_active_status(status, action="retire old switch interfaces")
            status = self.session.status()
            _require_active_status(status, action="retarget postcheck")
        except Exception as exc:
            message = (
                "The firewall allowlists could not be updated and verified; "
                "the firewall table was not deliberately disabled."
            )
            if operation == "switch":
                raise ProtectedServerSwitchError(
                    f"{message} Details: {exc}",
                    old_vpn_disconnected=True,
                ) from exc
            raise ProtectedReconnectError(f"{message} Details: {exc}") from exc
        self._emit(
            RecoveryPhase.FIREWALL_RETARGETED,
            "ok",
            "The exact protected endpoint route is active and verified.",
        )
        return status

    def _verify_postconnect(
        self,
        *,
        profile_uuid: str,
        operation: str,
        switch: bool,
    ) -> KillSwitchStatus:
        self._emit(
            RecoveryPhase.POSTCHECK_STARTED,
            "info",
            "The VPN and retained firewall lock are being verified together.",
        )
        try:
            if not self.vpn_backend.is_connected():
                raise RuntimeError("NetworkManager does not report an active VPN.")
            status = self.session.status()
            _require_active_status(status, action=f"{operation} postcheck")
            return status
        except Exception as exc:
            rollback_error = self._disconnect_if_active(profile_uuid)
            if switch:
                raise ProtectedServerSwitchError(
                    f"Post-switch verification failed; the new VPN was stopped where possible and the lock remains active: {exc}",
                    old_vpn_disconnected=True,
                    rollback_error=rollback_error,
                ) from exc
            raise ProtectedReconnectError(
                f"Post-reconnect verification failed; the VPN was stopped where possible and the lock remains active: {exc}",
                rollback_error=rollback_error,
            ) from exc

    def _disconnect_if_active(self, profile_uuid: str) -> str:
        self._emit(
            RecoveryPhase.ROLLBACK_STARTED,
            "error",
            "An unverified VPN is being stopped without changing the firewall lock.",
        )
        rollback_error = ""
        try:
            if self.vpn_backend.is_connected():
                self.vpn_backend.disconnect(profile_uuid)
        except Exception as exc:
            rollback_error = str(exc)
        else:
            self._emit(
                RecoveryPhase.ROLLBACK_COMPLETED,
                "warning",
                "The unverified VPN was stopped; the firewall lock was retained.",
            )
        return rollback_error

    def _emit(self, phase: RecoveryPhase, level: str, message: str) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink(RecoveryEvent(phase=phase, level=level, message=message))
        except Exception:
            return


def _require_route_plan(value: FirewallRoutePlan) -> FirewallRoutePlan:
    if not isinstance(value, FirewallRoutePlan):
        raise UnsafeRecoveryPlanError("Expected a firewall route plan.")
    return FirewallRoutePlan.create(
        physical_interfaces=value.physical_interfaces,
        endpoints=value.endpoints,
    )


def _require_active_status(status: KillSwitchStatus, *, action: str) -> None:
    if not isinstance(status, KillSwitchStatus) or not status.protection_active:
        raise RecoveryOrchestrationError(
            f"Kill-switch {action} did not return verified active protection."
        )


def _normalize_profile_uuid(value: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise UnsafeRecoveryPlanError("NetworkManager profile UUID is missing or unsafe.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise UnsafeRecoveryPlanError("NetworkManager profile UUID is invalid.") from exc
    return str(parsed)


def _normalize_interfaces(values: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise UnsafeRecoveryPlanError("Interface names must be strings.")
        if raw != raw.strip() or not _INTERFACE_PATTERN.fullmatch(raw):
            raise UnsafeRecoveryPlanError("Unsafe physical interface name.")
        if raw in {"lo", VPN_INTERFACE_NAME}:
            raise UnsafeRecoveryPlanError(
                f"Interface {raw!r} cannot be used as a physical interface."
            )
        normalized.add(raw)
    if not normalized:
        raise UnsafeRecoveryPlanError("At least one physical interface is required.")
    if len(normalized) > MAX_PHYSICAL_INTERFACES:
        raise UnsafeRecoveryPlanError("Too many physical interfaces were supplied.")
    return tuple(sorted(normalized))


def _normalize_endpoints(values: Iterable[str]) -> tuple[str, ...]:
    # Reuse ConnectionPlan's strict endpoint validation without requiring a file.
    normalized: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise UnsafeRecoveryPlanError("Endpoints must be strings.")
        temp = _normalize_endpoint_with_connection_parser(raw)
        normalized.add(temp)
    if not normalized:
        raise UnsafeRecoveryPlanError("At least one WireGuard endpoint is required.")
    if len(normalized) > MAX_ENDPOINTS:
        raise UnsafeRecoveryPlanError("Too many WireGuard endpoints were supplied.")
    return tuple(sorted(normalized))


def _normalize_endpoint_with_connection_parser(value: str) -> str:
    try:
        return normalize_wireguard_endpoint(value)
    except UnsafeConnectionPlanError as exc:
        raise UnsafeRecoveryPlanError(str(exc)) from exc


__all__ = [
    "FirewallRoutePlan",
    "KillSwitchRecoveryOrchestrator",
    "PreparedServerSwitch",
    "ProtectedReconnectError",
    "ProtectedReconnectResult",
    "ProtectedServerSwitchError",
    "ProtectedServerSwitchResult",
    "RecoveryEvent",
    "RecoveryOrchestrationError",
    "RecoveryPhase",
    "UnsafeRecoveryPlanError",
]
