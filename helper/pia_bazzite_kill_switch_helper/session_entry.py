from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import selectors
import sys
from typing import Any, Mapping, Sequence

from .cli import main as helper_main
from .core import HELPER_STAGE
from .protocol import PROTOCOL_VERSION, error_payload

SESSION_PROTOCOL_VERSION = 1
SESSION_SCHEMA_VERSION = 1
MAX_REQUESTS = 128
MAX_LINE_BYTES = 32 * 1024
IDLE_TIMEOUT_SECONDS = 12 * 60 * 60.0
EXIT_SESSION = 7

_ACTION_FIELDS: Mapping[str, frozenset[str]] = {
    "status": frozenset(),
    "enable": frozenset({"interfaces", "endpoints"}),
    "set-interfaces": frozenset({"interfaces"}),
    "set-endpoints": frozenset({"endpoints"}),
    "add-endpoint": frozenset({"endpoint"}),
    "remove-endpoint": frozenset({"endpoint"}),
    "disable": frozenset(),
    "emergency-reset": frozenset(),
    "ipv6-guard-status": frozenset(),
    "ipv6-guard-enable": frozenset(),
    "ipv6-guard-disable": frozenset(),
    "close": frozenset(),
}


class SessionProtocolError(ValueError):
    pass


def _emit(document: Mapping[str, Any]) -> None:
    line = json.dumps(dict(document), sort_keys=True, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _session_error(request_id: int, action: str, message: str) -> dict[str, Any]:
    return {
        "session_protocol_version": SESSION_PROTOCOL_VERSION,
        "session_schema_version": SESSION_SCHEMA_VERSION,
        "session_pid": os.getpid(),
        "request_id": request_id,
        "returncode": 2,
        "payload": error_payload(
            action=action,
            helper_stage=HELPER_STAGE,
            kind="session-validation",
            message=message,
        ),
    }


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise SessionProtocolError(f"Field {field!r} must be a non-empty string.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SessionProtocolError(f"Field {field!r} contains control characters.")
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise SessionProtocolError(f"Field {field!r} must be a non-empty string list.")
    return [_require_string(item, field) for item in value]


def _parse_request(document: Any, previous_request_id: int) -> tuple[int, str, list[str]]:
    if not isinstance(document, dict):
        raise SessionProtocolError("Session request must be a JSON object.")
    if "request_id" not in document or "action" not in document:
        raise SessionProtocolError("Session request requires request_id and action.")
    request_id = document["request_id"]
    if not isinstance(request_id, int) or isinstance(request_id, bool):
        raise SessionProtocolError("request_id must be an integer.")
    if request_id <= previous_request_id or request_id > 2_147_483_647:
        raise SessionProtocolError("request_id must increase monotonically.")
    action = _require_string(document["action"], "action")
    expected_fields = _ACTION_FIELDS.get(action)
    if expected_fields is None:
        raise SessionProtocolError("Unsupported session action.")
    actual_fields = set(document) - {"request_id", "action"}
    if actual_fields != set(expected_fields):
        raise SessionProtocolError("Session request fields do not match the action schema.")

    argv = [action]
    if action == "enable":
        for interface in _require_string_list(document["interfaces"], "interfaces"):
            argv.extend(("--interface", interface))
        for endpoint in _require_string_list(document["endpoints"], "endpoints"):
            argv.extend(("--endpoint", endpoint))
    elif action == "set-interfaces":
        for interface in _require_string_list(document["interfaces"], "interfaces"):
            argv.extend(("--interface", interface))
    elif action == "set-endpoints":
        for endpoint in _require_string_list(document["endpoints"], "endpoints"):
            argv.extend(("--endpoint", endpoint))
    elif action in {"add-endpoint", "remove-endpoint"}:
        argv.extend(("--endpoint", _require_string(document["endpoint"], "endpoint")))
    return request_id, action, argv


def _invoke_helper(
    argv: Sequence[str],
    *,
    trusted_host: bool = False,
) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        if trusted_host:
            returncode = helper_main(list(argv), trusted_host=True)
        else:
            returncode = helper_main(list(argv))
    output = stdout.getvalue() if returncode == 0 else stderr.getvalue()
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SessionProtocolError("Helper did not return exactly one JSON document.")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise SessionProtocolError("Helper returned malformed JSON.") from exc
    if not isinstance(payload, dict):
        raise SessionProtocolError("Helper JSON response is not an object.")
    return returncode, payload


def _read_line_with_timeout(timeout: float) -> bytes | None:
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.buffer, selectors.EVENT_READ)
    try:
        if not selector.select(timeout):
            return None
        line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
    finally:
        selector.close()
    if len(line) > MAX_LINE_BYTES:
        raise SessionProtocolError("Session request exceeds the fixed size limit.")
    return line


def main(*, trusted_host: bool = False) -> int:
    _emit(
        {
            "event": "ready",
            "session_protocol_version": SESSION_PROTOCOL_VERSION,
            "session_schema_version": SESSION_SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "helper_stage": HELPER_STAGE,
            "session_pid": os.getpid(),
            "max_requests": MAX_REQUESTS,
            "idle_timeout_seconds": int(IDLE_TIMEOUT_SECONDS),
        }
    )
    previous_request_id = 0
    for _ in range(MAX_REQUESTS):
        try:
            raw_line = _read_line_with_timeout(IDLE_TIMEOUT_SECONDS)
            if raw_line is None or raw_line == b"":
                return 0
            try:
                document = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SessionProtocolError("Session request is not valid UTF-8 JSON.") from exc
            request_id, action, argv = _parse_request(document, previous_request_id)
            previous_request_id = request_id
            if action == "close":
                _emit(
                    {
                        "session_protocol_version": SESSION_PROTOCOL_VERSION,
                        "session_schema_version": SESSION_SCHEMA_VERSION,
                        "session_pid": os.getpid(),
                        "request_id": request_id,
                        "returncode": 0,
                        "payload": {"ok": True, "action": "close"},
                    }
                )
                return 0
            returncode, payload = _invoke_helper(
                argv,
                trusted_host=trusted_host,
            )
            _emit(
                {
                    "session_protocol_version": SESSION_PROTOCOL_VERSION,
                    "session_schema_version": SESSION_SCHEMA_VERSION,
                    "session_pid": os.getpid(),
                    "request_id": request_id,
                    "returncode": returncode,
                    "payload": payload,
                }
            )
        except SessionProtocolError as exc:
            request_id = previous_request_id + 1
            action = "unknown"
            if isinstance(locals().get("document"), dict):
                raw_id = document.get("request_id")
                raw_action = document.get("action")
                if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id > 0:
                    request_id = raw_id
                if isinstance(raw_action, str) and raw_action in _ACTION_FIELDS:
                    action = raw_action
            _emit(_session_error(request_id, action, str(exc)))
    return EXIT_SESSION


__all__ = [
    "IDLE_TIMEOUT_SECONDS",
    "MAX_LINE_BYTES",
    "MAX_REQUESTS",
    "SESSION_PROTOCOL_VERSION",
    "SessionProtocolError",
    "main",
]
