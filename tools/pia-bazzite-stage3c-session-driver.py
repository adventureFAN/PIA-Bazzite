#!/usr/bin/python3 -I
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pia_bazzite.kill_switch_client import (
    AuthorizationDeniedError,
    HelperTimeoutError,
    InvalidHelperResponseError,
    KillSwitchClientError,
    KillSwitchStatus,
)
from pia_bazzite.kill_switch_session import KillSwitchSessionClient

BRIDGE_PATTERN = re.compile(
    r"/(?:usr/local|var/usrlocal)/libexec/pia-bazzite/"
    r"pia-bazzite-stage3c-session-netns-bridge-[0-9]{1,10}\Z"
)
OLD_ENDPOINTS = ("198.51.100.10:1337", "[2001:db8:100::10]:1337")
NEW_ENDPOINTS = ("198.51.100.11:1443", "[2001:db8:100::11]:1443")
OPERATIONS = {
    "status",
    "enable",
    "set-endpoints",
    "set-interfaces",
    "add-endpoint",
    "remove-endpoint",
    "disable",
    "emergency-reset",
    "close",
}


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def status_payload(status: KillSwitchStatus, session_pid: int) -> dict[str, object]:
    return {
        "controller_ok": True,
        "action": status.action,
        "state": status.state,
        "present": status.present,
        "verified": status.verified,
        "protection_active": status.protection_active,
        "table": status.table,
        "table_generation": status.table_generation,
        "session_pid": session_pid,
    }


def operation_callback(client: KillSwitchSessionClient, operation: str) -> Callable[[], KillSwitchStatus]:
    callbacks: dict[str, Callable[[], KillSwitchStatus]] = {
        "status": client.status,
        "enable": lambda: client.enable(interfaces=("wan0",), endpoints=OLD_ENDPOINTS),
        "set-endpoints": lambda: client.set_endpoints(NEW_ENDPOINTS),
        "set-interfaces": lambda: client.set_interfaces(("lan0",)),
        "add-endpoint": lambda: client.add_endpoint(OLD_ENDPOINTS[0]),
        "remove-endpoint": lambda: client.remove_endpoint(OLD_ENDPOINTS[0]),
        "disable": client.disable,
        "emergency-reset": client.emergency_reset,
    }
    return callbacks[operation]


def emit_error(kind: str, message: str) -> None:
    emit({"controller_ok": False, "kind": kind, "message": message})


def open_client(path: Path) -> KillSwitchSessionClient:
    client = KillSwitchSessionClient(session_path=path, timeout=60.0)
    client.open()
    return client


def denial_probe(path: Path) -> int:
    client = KillSwitchSessionClient(session_path=path, timeout=60.0)
    try:
        client.open()
    except AuthorizationDeniedError as exc:
        emit_error("authorization-denied", str(exc))
        return 20
    except KillSwitchClientError as exc:
        emit_error("client-error", str(exc))
        return 23
    try:
        client.close()
    finally:
        emit_error("authorization-unexpectedly-granted", "The denial probe was authorized.")
    return 24


def session_controller(path: Path) -> int:
    try:
        client = open_client(path)
    except AuthorizationDeniedError as exc:
        emit_error("authorization-denied", str(exc))
        return 20
    except KillSwitchClientError as exc:
        emit_error("client-error", str(exc))
        return 23
    session_pid = client.session_pid
    assert session_pid is not None
    emit({"controller_ok": True, "event": "ready", "session_pid": session_pid})
    try:
        for raw_line in sys.stdin:
            operation = raw_line.strip()
            if operation not in OPERATIONS:
                emit_error("controller-validation", "Unsupported fixed controller operation.")
                continue
            if operation == "close":
                client.close()
                emit({"controller_ok": True, "event": "closed", "session_pid": session_pid})
                return 0
            try:
                status = operation_callback(client, operation)()
                if client.session_pid != session_pid:
                    raise InvalidHelperResponseError("Broker PID changed during one session.")
                emit(status_payload(status, session_pid))
            except HelperTimeoutError as exc:
                emit_error("timeout", str(exc))
            except InvalidHelperResponseError as exc:
                emit_error("invalid-response", str(exc))
            except KillSwitchClientError as exc:
                emit_error("client-error", str(exc))
    finally:
        if client.is_open:
            client.close()
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        emit_error("usage", "Usage: driver BRIDGE {denial-probe|session}")
        return 2
    path = Path(sys.argv[1])
    if BRIDGE_PATTERN.fullmatch(str(path)) is None:
        emit_error("unsafe-test-path", "Bridge path is outside the fixed test scope.")
        return 2
    mode = sys.argv[2]
    if mode == "denial-probe":
        return denial_probe(path)
    if mode == "session":
        return session_controller(path)
    emit_error("usage", "Unsupported driver mode.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
