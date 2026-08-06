from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
import ipaddress
import os
from pathlib import Path
import re
import stat
from typing import Any, Protocol

from .kill_switch_client import KillSwitchStatus


VPN_INTERFACE_NAME = "piabazzite"
EXPECTED_CONFIG_NAME = f"{VPN_INTERFACE_NAME}.conf"
MAX_PHYSICAL_INTERFACES = 8
MAX_ENDPOINTS = 32
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


class ConnectionOrchestrationError(RuntimeError):
    """Base class for fail-closed connection orchestration errors."""


class UnsafeConnectionPlanError(ConnectionOrchestrationError):
    """Raised before any privileged or network action for an unsafe plan."""


class ServerSwitchDeferredError(ConnectionOrchestrationError):
    """The current staged path deliberately refuses a connected server switch."""


class KillSwitchPreparationError(ConnectionOrchestrationError):
    """The firewall lock could not be prepared and verified."""


class VpnStartError(ConnectionOrchestrationError):
    """The VPN failed to start after the firewall lock was prepared."""

    def __init__(self, message: str, *, firewall_retained: bool) -> None:
        super().__init__(message)
        self.firewall_retained = bool(firewall_retained)


class PostConnectVerificationError(ConnectionOrchestrationError):
    """The VPN or firewall failed verification after NetworkManager returned."""

    def __init__(
        self,
        message: str,
        *,
        firewall_retained: bool,
        rollback_error: str = "",
    ) -> None:
        super().__init__(message)
        self.firewall_retained = bool(firewall_retained)
        self.rollback_error = rollback_error


class IntentionalDisconnectError(ConnectionOrchestrationError):
    """A deliberate disconnect could not finish without weakening safety."""

    def __init__(
        self,
        message: str,
        *,
        vpn_disconnected: bool,
        firewall_retained: bool,
    ) -> None:
        super().__init__(message)
        self.vpn_disconnected = bool(vpn_disconnected)
        self.firewall_retained = bool(firewall_retained)


class ConnectionPhase(str, Enum):
    PLAN_VALIDATED = "plan-validated"
    KILL_SWITCH_BYPASSED = "kill-switch-bypassed"
    AUTHORIZATION_STARTED = "authorization-started"
    SESSION_AUTHORIZED = "session-authorized"
    FIREWALL_PREPARED = "firewall-prepared"
    VPN_STARTING = "vpn-starting"
    VPN_STARTED = "vpn-started"
    POSTCHECK_STARTED = "postcheck-started"
    CONNECTION_VERIFIED = "connection-verified"
    ROLLBACK_STARTED = "rollback-started"
    ROLLBACK_COMPLETED = "rollback-completed"
    DISCONNECT_PREFLIGHT_STARTED = "disconnect-preflight-started"
    DISCONNECT_PREFLIGHT_VERIFIED = "disconnect-preflight-verified"
    VPN_STOPPING = "vpn-stopping"
    VPN_STOPPED = "vpn-stopped"
    BLOCKED_PATH_CHECK_STARTED = "blocked-path-check-started"
    BLOCKED_PATH_VERIFIED = "blocked-path-verified"
    FIREWALL_RELEASING = "firewall-releasing"
    FIREWALL_RELEASED = "firewall-released"
    INTENTIONAL_DISCONNECT_VERIFIED = "intentional-disconnect-verified"


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    phase: ConnectionPhase
    level: str
    message: str


@dataclass(frozen=True, slots=True)
class ConnectionPlan:
    """Fully prepared, strictly validated input for one VPN start.

    The staged path expects the PIA API work and WireGuard configuration creation to
    have completed before this object is built. That gives the orchestrator the
    exact numeric endpoint needed for the firewall rule before NetworkManager
    is allowed to start the tunnel.
    """

    config_path: Path
    physical_interfaces: tuple[str, ...]
    endpoints: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        config_path: Path,
        physical_interfaces: Iterable[str],
        endpoints: Iterable[str],
    ) -> "ConnectionPlan":
        path = _validate_config_path(Path(config_path))
        interfaces = _normalize_interfaces(physical_interfaces)
        normalized_endpoints = _normalize_endpoints(endpoints)
        if len(normalized_endpoints) != 1:
            raise UnsafeConnectionPlanError(
                "The current staged path requires exactly one WireGuard endpoint."
            )
        return cls(
            config_path=path,
            physical_interfaces=interfaces,
            endpoints=normalized_endpoints,
        )

    def verify_config_file(self) -> None:
        _verify_config_file(
            self.config_path,
            expected_endpoint=self.endpoints[0],
        )


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    profile_uuid: str
    kill_switch_enabled: bool
    firewall_status: KillSwitchStatus | None
    plan: ConnectionPlan


@dataclass(frozen=True, slots=True)
class IntentionalDisconnectResult:
    kill_switch_enabled: bool
    vpn_disconnected: bool
    firewall_status: KillSwitchStatus | None


class KillSwitchSessionLike(Protocol):
    def open(self) -> Any:
        ...

    def enable(
        self,
        *,
        interfaces: Sequence[str],
        endpoints: Sequence[str],
    ) -> KillSwitchStatus:
        ...

    def status(self) -> KillSwitchStatus:
        ...

    def disable(self) -> KillSwitchStatus:
        ...


class VpnBackend(Protocol):
    def connect(self, config_path: Path) -> str:
        ...

    def is_connected(self) -> bool:
        ...

    def disconnect(self, profile_uuid: str = "") -> None:
        ...


class KillSwitchConnectionOrchestrator:
    """Prepare the firewall first, then start and verify the VPN.

    This stage does not discover interfaces, create WireGuard configuration,
    install the helper, alter settings, or implement server switching. Those
    responsibilities remain outside this small, deterministic safety boundary.
    """

    def __init__(
        self,
        *,
        session: KillSwitchSessionLike,
        vpn_backend: VpnBackend,
        event_sink: Callable[[ConnectionEvent], None] | None = None,
    ) -> None:
        self.session = session
        self.vpn_backend = vpn_backend
        self.event_sink = event_sink

    def connect(
        self,
        plan: ConnectionPlan,
        *,
        kill_switch_enabled: bool,
        vpn_connected_before: bool = False,
    ) -> ConnectionResult:
        plan.verify_config_file()
        self._emit(
            ConnectionPhase.PLAN_VALIDATED,
            "info",
            "WireGuard configuration, physical interfaces, and endpoint are validated.",
        )

        if vpn_connected_before:
            raise ServerSwitchDeferredError(
                "The current staged path refuses server switching while a VPN is already connected."
            )

        firewall_status: KillSwitchStatus | None = None
        if kill_switch_enabled:
            firewall_status = self._prepare_firewall(plan)
        else:
            self._emit(
                ConnectionPhase.KILL_SWITCH_BYPASSED,
                "warning",
                "Kill switch is disabled; the existing VPN-only path is used.",
            )

        self._emit(
            ConnectionPhase.VPN_STARTING,
            "info",
            "NetworkManager may start the WireGuard profile now.",
        )
        try:
            profile_uuid = str(self.vpn_backend.connect(plan.config_path)).strip()
        except Exception as exc:
            raise VpnStartError(
                f"VPN start failed: {exc}",
                firewall_retained=kill_switch_enabled,
            ) from exc

        self._emit(
            ConnectionPhase.VPN_STARTED,
            "info",
            "NetworkManager returned from the VPN start request.",
        )
        self._emit(
            ConnectionPhase.POSTCHECK_STARTED,
            "info",
            "VPN and kill-switch state are being verified.",
        )

        if not profile_uuid:
            self._rollback_after_postcheck_failure(
                "NetworkManager returned no profile UUID.",
                profile_uuid="",
                firewall_retained=kill_switch_enabled,
            )

        try:
            vpn_connected = bool(self.vpn_backend.is_connected())
        except Exception as exc:
            self._rollback_after_postcheck_failure(
                f"VPN state verification failed: {exc}",
                profile_uuid=profile_uuid,
                firewall_retained=kill_switch_enabled,
            )
        if not vpn_connected:
            self._rollback_after_postcheck_failure(
                "NetworkManager did not report an active VPN after connection.",
                profile_uuid=profile_uuid,
                firewall_retained=kill_switch_enabled,
            )

        if kill_switch_enabled:
            try:
                firewall_status = self.session.status()
                _require_verified_active_status(firewall_status, action="status")
            except Exception as exc:
                self._rollback_after_postcheck_failure(
                    f"Kill-switch post-connect verification failed: {exc}",
                    profile_uuid=profile_uuid,
                    firewall_retained=True,
                )

        self._emit(
            ConnectionPhase.CONNECTION_VERIFIED,
            "ok",
            "The VPN connection and requested protection state are verified.",
        )
        return ConnectionResult(
            profile_uuid=profile_uuid,
            kill_switch_enabled=bool(kill_switch_enabled),
            firewall_status=firewall_status,
            plan=plan,
        )

    def disconnect_intentionally(
        self,
        *,
        profile_uuid: str = "",
        kill_switch_enabled: bool,
        blocked_path_probe: Callable[[], bool] | None = None,
    ) -> IntentionalDisconnectResult:
        """Disconnect the VPN and only then deliberately release the firewall.

        With the optional kill switch enabled, this method first verifies that
        the firewall lock is active. It then stops and verifies the VPN while
        retaining that lock. An optional independent probe may prove that the
        ordinary path is blocked before the helper is allowed to disable the
        table. Any failure before a verified disable remains fail-closed.
        """

        if not kill_switch_enabled:
            self._emit(
                ConnectionPhase.KILL_SWITCH_BYPASSED,
                "warning",
                "Kill switch is disabled; only the VPN is intentionally disconnected.",
            )
            self._disconnect_vpn_and_verify(profile_uuid, firewall_retained=False)
            self._emit(
                ConnectionPhase.INTENTIONAL_DISCONNECT_VERIFIED,
                "ok",
                "The VPN is intentionally disconnected and the normal connection may be used.",
            )
            return IntentionalDisconnectResult(
                kill_switch_enabled=False,
                vpn_disconnected=True,
                firewall_status=None,
            )

        self._emit(
            ConnectionPhase.DISCONNECT_PREFLIGHT_STARTED,
            "info",
            "The active firewall lock is being verified before the VPN is stopped.",
        )
        try:
            self.session.open()
            active_status = self.session.status()
            _require_verified_active_status(active_status, action="disconnect preflight")
        except Exception as exc:
            raise IntentionalDisconnectError(
                f"Intentional disconnect was refused because the active firewall lock "
                f"could not be verified: {exc}",
                vpn_disconnected=False,
                firewall_retained=True,
            ) from exc

        self._emit(
            ConnectionPhase.DISCONNECT_PREFLIGHT_VERIFIED,
            "ok",
            "The firewall lock is verified and will remain active while the VPN stops.",
        )
        self._disconnect_vpn_and_verify(profile_uuid, firewall_retained=True)

        if blocked_path_probe is not None:
            self._emit(
                ConnectionPhase.BLOCKED_PATH_CHECK_STARTED,
                "info",
                "The ordinary network path is being probed while the firewall lock remains active.",
            )
            try:
                blocked = bool(blocked_path_probe())
            except Exception as exc:
                raise IntentionalDisconnectError(
                    f"The blocked-path probe failed; the firewall lock remains active: {exc}",
                    vpn_disconnected=True,
                    firewall_retained=True,
                ) from exc
            if not blocked:
                raise IntentionalDisconnectError(
                    "The ordinary network path was not proven blocked; the firewall lock remains active.",
                    vpn_disconnected=True,
                    firewall_retained=True,
                )
            self._emit(
                ConnectionPhase.BLOCKED_PATH_VERIFIED,
                "ok",
                "The ordinary network path is blocked while the VPN is disconnected.",
            )

        self._emit(
            ConnectionPhase.FIREWALL_RELEASING,
            "warning",
            "The verified firewall lock is being deliberately released.",
        )
        try:
            disabled_status = self.session.disable()
            _require_verified_disabled_status(disabled_status, action="disable")
        except Exception as exc:
            raise IntentionalDisconnectError(
                f"The VPN is disconnected, but the firewall lock could not be "
                f"verified as disabled: {exc}",
                vpn_disconnected=True,
                firewall_retained=True,
            ) from exc

        self._emit(
            ConnectionPhase.FIREWALL_RELEASED,
            "ok",
            "The firewall lock is disabled and verified absent.",
        )
        self._emit(
            ConnectionPhase.INTENTIONAL_DISCONNECT_VERIFIED,
            "ok",
            "The VPN and kill switch are intentionally disconnected; normal internet access may resume.",
        )
        return IntentionalDisconnectResult(
            kill_switch_enabled=True,
            vpn_disconnected=True,
            firewall_status=disabled_status,
        )

    def _prepare_firewall(self, plan: ConnectionPlan) -> KillSwitchStatus:
        self._emit(
            ConnectionPhase.AUTHORIZATION_STARTED,
            "info",
            "The restricted kill-switch session is being authorized.",
        )
        try:
            self.session.open()
        except Exception as exc:
            raise KillSwitchPreparationError(
                f"Kill-switch authorization or session start failed: {exc}"
            ) from exc
        self._emit(
            ConnectionPhase.SESSION_AUTHORIZED,
            "info",
            "The restricted kill-switch session is ready.",
        )

        try:
            status = self.session.enable(
                interfaces=plan.physical_interfaces,
                endpoints=plan.endpoints,
            )
            _require_verified_active_status(status, action="enable")
        except Exception as exc:
            raise KillSwitchPreparationError(
                f"The firewall lock could not be prepared and verified: {exc}"
            ) from exc

        self._emit(
            ConnectionPhase.FIREWALL_PREPARED,
            "ok",
            "The firewall lock is active and verified before VPN startup.",
        )
        return status

    def _rollback_after_postcheck_failure(
        self,
        message: str,
        *,
        profile_uuid: str,
        firewall_retained: bool,
    ) -> None:
        self._emit(
            ConnectionPhase.ROLLBACK_STARTED,
            "error",
            "Post-connect verification failed; the VPN is being disconnected.",
        )
        rollback_error = ""
        try:
            self.vpn_backend.disconnect(profile_uuid)
        except Exception as exc:
            rollback_error = str(exc)
        else:
            self._emit(
                ConnectionPhase.ROLLBACK_COMPLETED,
                "warning",
                "The unverified VPN connection was disconnected; the firewall state was not relaxed.",
            )
        raise PostConnectVerificationError(
            message,
            firewall_retained=firewall_retained,
            rollback_error=rollback_error,
        )

    def _disconnect_vpn_and_verify(
        self,
        profile_uuid: str,
        *,
        firewall_retained: bool,
    ) -> None:
        self._emit(
            ConnectionPhase.VPN_STOPPING,
            "info",
            "NetworkManager is intentionally stopping the WireGuard profile.",
        )
        try:
            self.vpn_backend.disconnect(profile_uuid)
        except Exception as exc:
            raise IntentionalDisconnectError(
                f"VPN disconnect failed: {exc}",
                vpn_disconnected=False,
                firewall_retained=firewall_retained,
            ) from exc
        try:
            still_connected = bool(self.vpn_backend.is_connected())
        except Exception as exc:
            raise IntentionalDisconnectError(
                f"VPN disconnect verification failed: {exc}",
                vpn_disconnected=False,
                firewall_retained=firewall_retained,
            ) from exc
        if still_connected:
            raise IntentionalDisconnectError(
                "NetworkManager still reports an active VPN after disconnect.",
                vpn_disconnected=False,
                firewall_retained=firewall_retained,
            )
        self._emit(
            ConnectionPhase.VPN_STOPPED,
            "ok",
            "The VPN is verified disconnected; the firewall state has not been relaxed.",
        )

    def _emit(self, phase: ConnectionPhase, level: str, message: str) -> None:
        sink = self.event_sink
        if sink is None:
            return
        try:
            sink(ConnectionEvent(phase=phase, level=level, message=message))
        except Exception:
            # Logging/UI callbacks must never weaken or interrupt the safety flow.
            return


def _require_verified_active_status(
    status: KillSwitchStatus,
    *,
    action: str,
) -> None:
    if not isinstance(status, KillSwitchStatus):
        raise KillSwitchPreparationError(
            f"Kill-switch {action} returned an unexpected object."
        )
    if not status.protection_active:
        raise KillSwitchPreparationError(
            f"Kill-switch {action} did not return verified active protection."
        )


def _require_verified_disabled_status(
    status: KillSwitchStatus,
    *,
    action: str,
) -> None:
    if not isinstance(status, KillSwitchStatus):
        raise IntentionalDisconnectError(
            f"Kill-switch {action} returned an unexpected object.",
            vpn_disconnected=True,
            firewall_retained=True,
        )
    if status.state != "disabled" or status.present or not status.verified or status.problems:
        raise IntentionalDisconnectError(
            f"Kill-switch {action} did not return a verified disabled state.",
            vpn_disconnected=True,
            firewall_retained=True,
        )


def _validate_config_path(path: Path) -> Path:
    if not path.is_absolute():
        raise UnsafeConnectionPlanError("WireGuard configuration path must be absolute.")
    if path.name != EXPECTED_CONFIG_NAME:
        raise UnsafeConnectionPlanError(
            f"WireGuard configuration must be named {EXPECTED_CONFIG_NAME!r}."
        )
    if any(ord(character) < 32 for character in str(path)):
        raise UnsafeConnectionPlanError(
            "WireGuard configuration path contains control characters."
        )
    return path


def _verify_config_file(path: Path, *, expected_endpoint: str) -> None:
    configured_endpoint = read_wireguard_endpoint(path)
    if configured_endpoint != expected_endpoint:
        raise UnsafeConnectionPlanError(
            "WireGuard configuration endpoint does not match the firewall allowlist."
        )


def read_wireguard_endpoint(path: Path) -> str:
    """Read one numeric endpoint from a private fixed-name config file."""

    path = _validate_config_path(Path(path))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UnsafeConnectionPlanError(
            f"WireGuard configuration cannot be inspected: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise UnsafeConnectionPlanError(
            "WireGuard configuration must be a regular file and not a symlink."
        )
    if metadata.st_uid != os.getuid():
        raise UnsafeConnectionPlanError(
            "WireGuard configuration must be owned by the current user."
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise UnsafeConnectionPlanError(
            "WireGuard configuration must not be accessible by group or others."
        )
    if metadata.st_size <= 0 or metadata.st_size > 128 * 1024:
        raise UnsafeConnectionPlanError(
            "WireGuard configuration has an invalid size."
        )
    try:
        config_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UnsafeConnectionPlanError(
            f"WireGuard configuration cannot be read safely: {exc}"
        ) from exc
    return _extract_wireguard_endpoint(config_text)


def _extract_wireguard_endpoint(config_text: str) -> str:
    in_peer = False
    endpoints: list[str] = []
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_peer = line.casefold() == "[peer]"
            continue
        if not in_peer or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().casefold() == "endpoint":
            canonical, _, _, _ = _normalize_endpoint(value.strip())
            endpoints.append(canonical)
    if len(endpoints) != 1:
        raise UnsafeConnectionPlanError(
            "WireGuard configuration must contain exactly one numeric peer endpoint."
        )
    return endpoints[0]


def _normalize_interfaces(values: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise UnsafeConnectionPlanError("Interface names must be strings.")
        if raw != raw.strip() or not _INTERFACE_PATTERN.fullmatch(raw):
            raise UnsafeConnectionPlanError("Unsafe physical interface name.")
        if raw in {"lo", VPN_INTERFACE_NAME}:
            raise UnsafeConnectionPlanError(
                f"Interface {raw!r} cannot be used as a physical interface."
            )
        normalized.add(raw)
    if not normalized:
        raise UnsafeConnectionPlanError("At least one physical interface is required.")
    if len(normalized) > MAX_PHYSICAL_INTERFACES:
        raise UnsafeConnectionPlanError("Too many physical interfaces were supplied.")
    return tuple(sorted(normalized))


def normalize_wireguard_endpoint(value: str) -> str:
    """Return one canonical numeric WireGuard endpoint after strict validation."""

    canonical, _, _, _ = _normalize_endpoint(value)
    return canonical


def _normalize_endpoints(values: Iterable[str]) -> tuple[str, ...]:
    normalized: set[tuple[int, int, int, str]] = set()
    for raw in values:
        canonical, family, numeric_address, port = _normalize_endpoint(raw)
        normalized.add((family, numeric_address, port, canonical))
    if not normalized:
        raise UnsafeConnectionPlanError("At least one WireGuard endpoint is required.")
    if len(normalized) > MAX_ENDPOINTS:
        raise UnsafeConnectionPlanError("Too many WireGuard endpoints were supplied.")
    return tuple(item[3] for item in sorted(normalized))


def _normalize_endpoint(value: str) -> tuple[str, int, int, int]:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise UnsafeConnectionPlanError("Endpoint must be a non-empty trimmed string.")

    if value.startswith("["):
        close = value.find("]")
        if close <= 1 or close + 1 >= len(value) or value[close + 1] != ":":
            raise UnsafeConnectionPlanError(
                "IPv6 endpoints must use [address]:port syntax."
            )
        host = value[1:close]
        port_text = value[close + 2 :]
    else:
        if value.count(":") != 1:
            raise UnsafeConnectionPlanError(
                "IPv4 endpoints must use address:port syntax."
            )
        host, port_text = value.rsplit(":", 1)

    if not port_text.isascii() or not port_text.isdecimal():
        raise UnsafeConnectionPlanError("Endpoint port must be decimal.")
    port = int(port_text, 10)
    if not 1 <= port <= 65535:
        raise UnsafeConnectionPlanError("Endpoint port is outside the valid range.")

    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise UnsafeConnectionPlanError(
            "Endpoint address must be numeric IPv4 or IPv6."
        ) from exc
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local:
        raise UnsafeConnectionPlanError("Unsafe special-purpose endpoint address.")
    if isinstance(address, ipaddress.IPv6Address) and address.scope_id is not None:
        raise UnsafeConnectionPlanError("Scoped IPv6 endpoints are not allowed.")

    canonical = (
        f"[{address.compressed}]:{port}"
        if address.version == 6
        else f"{address.compressed}:{port}"
    )
    return canonical, address.version, int(address), port


__all__ = [
    "ConnectionEvent",
    "ConnectionOrchestrationError",
    "ConnectionPhase",
    "ConnectionPlan",
    "ConnectionResult",
    "IntentionalDisconnectError",
    "IntentionalDisconnectResult",
    "KillSwitchConnectionOrchestrator",
    "KillSwitchPreparationError",
    "PostConnectVerificationError",
    "ServerSwitchDeferredError",
    "UnsafeConnectionPlanError",
    "VpnStartError",
    "normalize_wireguard_endpoint",
    "read_wireguard_endpoint",
]
