#!/usr/bin/python3 -I
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pia_bazzite.kill_switch_client import (  # noqa: E402
    AuthorizationDeniedError,
    HelperTimeoutError,
    InvalidHelperResponseError,
    KillSwitchClient,
    KillSwitchClientError,
    KillSwitchStatus,
)

BRIDGE_PATTERN = re.compile(
    r"/usr/local/libexec/pia-bazzite/"
    r"pia-bazzite-stage3-client-netns-bridge-[0-9]{1,10}\Z"
)
PROBE_PATTERN = re.compile(
    r"/usr/local/libexec/pia-bazzite/"
    r"pia-bazzite-stage3-(invalid-response|timeout)-probe\Z"
)
SHIM_PATH = Path(
    "/usr/local/libexec/pia-bazzite/pia-bazzite-stage3-process-shim"
)

OLD_ENDPOINTS = ("198.51.100.10:1337", "[2001:db8:100::10]:1337")
NEW_ENDPOINTS = ("198.51.100.11:1443", "[2001:db8:100::11]:1443")


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def status_payload(status: KillSwitchStatus) -> dict[str, object]:
    return {
        "client_ok": True,
        "action": status.action,
        "state": status.state,
        "present": status.present,
        "verified": status.verified,
        "protection_active": status.protection_active,
        "table": status.table,
        "table_generation": status.table_generation,
    }


def run_operation(client: KillSwitchClient, operation: str) -> KillSwitchStatus:
    operations: dict[str, Callable[[], KillSwitchStatus]] = {
        "status": client.status,
        "enable": lambda: client.enable(interfaces=("wan0",), endpoints=OLD_ENDPOINTS),
        "set-endpoints": lambda: client.set_endpoints(NEW_ENDPOINTS),
        "set-interfaces": lambda: client.set_interfaces(("lan0",)),
        "add-endpoint": lambda: client.add_endpoint(OLD_ENDPOINTS[0]),
        "remove-endpoint": lambda: client.remove_endpoint(OLD_ENDPOINTS[0]),
        "disable": client.disable,
        "emergency-reset": client.emergency_reset,
    }
    try:
        callback = operations[operation]
    except KeyError as exc:
        raise ValueError("Unsupported fixed stage-3 client operation.") from exc
    return callback()


def main() -> int:
    if len(sys.argv) not in (3, 4):
        emit({"client_ok": False, "kind": "usage"})
        return 2
    helper_path = Path(sys.argv[1])
    operation = sys.argv[2]
    path_text = str(helper_path)
    if BRIDGE_PATTERN.fullmatch(path_text) is None and PROBE_PATTERN.fullmatch(path_text) is None:
        emit({"client_ok": False, "kind": "unsafe-test-path"})
        return 2
    timeout = 1.0 if operation == "timeout-probe" else 60.0
    requested_operation = "status" if operation in {"invalid-response-probe", "timeout-probe"} else operation
    pkexec_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    if pkexec_path is not None and pkexec_path != SHIM_PATH:
        emit({"client_ok": False, "kind": "unsafe-pkexec-test-path"})
        return 2
    kwargs = {"helper_path": helper_path, "timeout": timeout}
    if pkexec_path is not None:
        kwargs["pkexec_path"] = pkexec_path
    client = KillSwitchClient(**kwargs)
    try:
        status = run_operation(client, requested_operation)
    except AuthorizationDeniedError as exc:
        emit({"client_ok": False, "kind": "authorization-denied", "message": str(exc)})
        return 20
    except HelperTimeoutError as exc:
        emit({"client_ok": False, "kind": "timeout", "message": str(exc)})
        return 21
    except InvalidHelperResponseError as exc:
        emit({"client_ok": False, "kind": "invalid-response", "message": str(exc)})
        return 22
    except KillSwitchClientError as exc:
        emit({"client_ok": False, "kind": "client-error", "message": str(exc)})
        return 23
    except (TypeError, ValueError) as exc:
        emit({"client_ok": False, "kind": "driver-validation", "message": str(exc)})
        return 2
    emit(status_payload(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
