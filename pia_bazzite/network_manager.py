from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import uuid

from .app_errors import AppError


CONNECTION_NAME = "PIA Bazzite"
INTERFACE_NAME = "piabazzite"
IPV4_PROBE_TARGET = "1.1.1.1"


class NetworkManagerError(AppError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectionState:
    connected: bool
    uuid: str = ""


def _run(
    arguments: list[str],
    *,
    check: bool = True,
    timeout: float = 45.0,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise NetworkManagerError(
            "error.nm_missing.title",
            "error.nm_missing.message",
            details=str(exc),
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NetworkManagerError(
            "error.nm_timeout.title",
            "error.nm_timeout.message",
            details=str(exc),
        ) from exc
    except OSError as exc:
        raise NetworkManagerError(
            "error.nm_generic.title",
            "error.nm_generic.message",
            details=str(exc),
        ) from exc

    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Unknown error").strip()
        lowered = detail.casefold()
        if "not authorized" in lowered or "nicht berechtigt" in lowered:
            raise NetworkManagerError(
                "error.nm_authorization.title",
                "error.nm_authorization.message",
                details=detail,
            )
        raise NetworkManagerError(
            "error.nm_profile.title",
            "error.nm_profile.message",
            details=detail,
        )
    return completed


def ensure_available() -> None:
    if shutil.which("nmcli") is None:
        raise NetworkManagerError(
            "error.nm_missing.title",
            "error.nm_missing.message",
        )


def connection_state() -> ConnectionState:
    ensure_available()
    completed = _run(
        ["nmcli", "-t", "-f", "UUID,NAME,TYPE", "connection", "show", "--active"],
        timeout=10,
    )
    for line in completed.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        uuid, name, connection_type = parts
        if name == CONNECTION_NAME and connection_type == "wireguard":
            return ConnectionState(True, uuid)
    return ConnectionState(False)


def is_connected() -> bool:
    return connection_state().connected


def _delete_profile(identifier: str) -> None:
    if identifier:
        _run(
            ["nmcli", "connection", "delete", "id", identifier],
            check=False,
            timeout=20,
        )


def _delete_existing_profiles() -> None:
    state = connection_state()
    if state.connected:
        _run(
            ["nmcli", "connection", "down", "uuid", state.uuid],
            check=False,
            timeout=30,
        )
    for identifier in (CONNECTION_NAME, INTERFACE_NAME):
        _delete_profile(identifier)


def _normalize_profile_uuid(value: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise NetworkManagerError(
            "error.nm_profile.title",
            "error.nm_profile.message",
            details="NetworkManager profile UUID is missing or invalid.",
        )
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise NetworkManagerError(
            "error.nm_profile.title",
            "error.nm_profile.message",
            details="NetworkManager profile UUID is missing or invalid.",
        ) from exc


def _profile_is_available(profile_uuid: str) -> bool:
    completed = _run(
        ["nmcli", "-t", "-f", "UUID,NAME,TYPE", "connection", "show"],
        timeout=15,
    )
    for line in completed.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        uuid_value, name, connection_type = parts
        if (
            uuid_value == profile_uuid
            and name == CONNECTION_NAME
            and connection_type == "wireguard"
        ):
            return True
    return False


def connect(config_path: Path) -> str:
    ensure_available()
    if not config_path.is_file():
        raise NetworkManagerError(
            "error.config_missing.title",
            "error.config_missing.message",
            details=str(config_path),
        )
    if config_path.stem != INTERFACE_NAME:
        raise NetworkManagerError(
            "error.interface_invalid.title",
            "error.interface_invalid.message",
            details=f"Expected: {INTERFACE_NAME}.conf; received: {config_path.name}",
        )

    _delete_existing_profiles()
    _run(
        ["nmcli", "connection", "import", "type", "wireguard", "file", str(config_path)],
        timeout=45,
    )
    _run([
        "nmcli", "connection", "modify", INTERFACE_NAME,
        "connection.id", CONNECTION_NAME,
        "connection.autoconnect", "no",
        "connection.interface-name", INTERFACE_NAME,
        "ipv4.dns-priority", "-50",
        "ipv4.dns-search", "~.",
    ])
    _run([
        "nmcli", "connection", "modify", CONNECTION_NAME,
        "ipv6.method", "disabled",
        "ipv6.never-default", "yes",
    ])
    _run(
        ["nmcli", "connection", "up", "id", CONNECTION_NAME],
        timeout=60,
    )

    state = connection_state()
    if not state.connected:
        raise NetworkManagerError(
            "error.vpn_not_active.title",
            "error.vpn_not_active.message",
        )
    if not vpn_ipv4_route_active():
        _run(
            ["nmcli", "connection", "down", "uuid", state.uuid],
            check=False,
            timeout=30,
        )
        raise NetworkManagerError(
            "error.vpn_not_active.title",
            "error.vpn_not_active.message",
            details=(
                "The PIA profile became active, but the effective public IPv4 route "
                "did not select the PIA WireGuard interface. The VPN was disconnected again."
            ),
        )
    return state.uuid


def reconnect(profile_uuid: str) -> str:
    """Reactivate one existing fixed PIA WireGuard profile by UUID."""

    ensure_available()
    profile = _normalize_profile_uuid(profile_uuid)
    state = connection_state()
    if state.connected:
        raise NetworkManagerError(
            "error.nm_profile.title",
            "error.nm_profile.message",
            details="Protected reconnect requires the PIA VPN to be disconnected first.",
        )
    if not _profile_is_available(profile):
        raise NetworkManagerError(
            "error.nm_profile.title",
            "error.nm_profile.message",
            details="The expected inactive PIA WireGuard profile is unavailable.",
        )
    _run(
        ["nmcli", "connection", "up", "uuid", profile],
        timeout=60,
    )
    state = connection_state()
    if not state.connected or state.uuid != profile:
        raise NetworkManagerError(
            "error.vpn_not_active.title",
            "error.vpn_not_active.message",
            details="NetworkManager did not reactivate the requested profile UUID.",
        )
    if not vpn_ipv4_route_active():
        _run(
            ["nmcli", "connection", "down", "uuid", state.uuid],
            check=False,
            timeout=30,
        )
        raise NetworkManagerError(
            "error.vpn_not_active.title",
            "error.vpn_not_active.message",
            details=(
                "The PIA profile was reactivated, but the effective public IPv4 route "
                "did not select the PIA WireGuard interface. The VPN was disconnected again."
            ),
        )
    return state.uuid


def disconnect(profile_uuid: str = "") -> None:
    ensure_available()
    state = connection_state()
    if not state.connected:
        return
    identifier = profile_uuid if profile_uuid and profile_uuid == state.uuid else state.uuid
    completed = _run(
        ["nmcli", "connection", "down", "uuid", identifier],
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        # Do not trust localized nmcli error prose as proof that the VPN is
        # absent.  Re-read the fixed active-state query and accept the failed
        # down operation only when absence is independently verified.
        verified = connection_state()
        if not verified.connected:
            return
        detail = (completed.stderr or completed.stdout).strip()
        raise NetworkManagerError(
            "error.disconnect.title",
            "error.disconnect.message",
            details=detail or "NetworkManager still reports the PIA VPN as active.",
        )



def vpn_ipv4_route_active() -> bool:
    """Return True only when public IPv4 selects the fixed PIA interface."""

    if shutil.which("ip") is None:
        return False
    selected = _run(
        ["ip", "-4", "route", "get", IPV4_PROBE_TARGET],
        check=False,
        timeout=10,
    )
    if selected.returncode != 0:
        return False
    fields = selected.stdout.strip().split()
    try:
        index = fields.index("dev")
        return fields[index + 1] == INTERFACE_NAME
    except (ValueError, IndexError):
        return False
