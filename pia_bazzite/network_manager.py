from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

from .app_errors import AppError


CONNECTION_NAME = "PIA Bazzite"
INTERFACE_NAME = "piabazzite"


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
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        return ConnectionState(False)
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
        "ipv6.method", "manual",
        "ipv6.addresses", "fd42:5049:4100::3/128",
        "ipv6.routes", "::/0 type=blackhole",
        "ipv6.never-default", "no",
        "ipv6.may-fail", "yes",
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
        detail = (completed.stderr or completed.stdout).strip()
        if "not active" not in detail.casefold() and "nicht aktiv" not in detail.casefold():
            raise NetworkManagerError(
                "error.disconnect.title",
                "error.disconnect.message",
                details=detail,
            )


def ipv6_blackhole_active() -> bool:
    if shutil.which("ip") is None:
        return False
    completed = _run(
        ["ip", "-6", "route", "show", "type", "blackhole", "default"],
        check=False,
        timeout=10,
    )
    return completed.returncode == 0 and "blackhole default" in completed.stdout
