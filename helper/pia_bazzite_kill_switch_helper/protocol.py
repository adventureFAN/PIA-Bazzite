from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

PROTOCOL_VERSION = 1
SCHEMA_VERSION = 1

ACTIONS = (
    "status",
    "enable",
    "set-interfaces",
    "set-endpoints",
    "add-endpoint",
    "remove-endpoint",
    "disable",
    "emergency-reset",
    "ipv6-guard-status",
    "ipv6-guard-enable",
    "ipv6-guard-disable",
)


class ProtocolError(ValueError):
    """Raised when a helper request or response violates protocol v1."""


@dataclass(frozen=True, slots=True)
class RequestContext:
    action: str | None

    @property
    def response_action(self) -> str:
        return self.action if self.action in ACTIONS else "unknown"


def infer_action(argv: Sequence[str] | None) -> RequestContext:
    values = list(argv or ())
    for value in values:
        if value in ACTIONS:
            return RequestContext(value)
        if not value.startswith("-"):
            return RequestContext(value)
    return RequestContext(None)


def success_payload(
    *,
    action: str,
    helper_stage: int,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise ProtocolError(f"Unsupported success action: {action}")
    payload: dict[str, Any] = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "helper_stage": helper_stage,
        "action": action,
    }
    if fields:
        for key, value in fields.items():
            if key in payload and payload[key] != value:
                raise ProtocolError(f"Response field {key!r} conflicts with the protocol envelope.")
            payload[key] = value
    return payload


def error_payload(
    *,
    action: str | None,
    helper_stage: int,
    kind: str,
    message: str,
) -> dict[str, Any]:
    if not isinstance(kind, str) or not kind:
        raise ProtocolError("Error kind must be a non-empty string.")
    if not isinstance(message, str) or not message:
        raise ProtocolError("Error message must be a non-empty string.")
    context = RequestContext(action)
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "helper_stage": helper_stage,
        "action": context.response_action,
        "error": kind,
        "message": message,
    }


def validate_payload(payload: Mapping[str, Any]) -> None:
    required = {
        "ok",
        "schema_version",
        "protocol_version",
        "helper_stage",
        "action",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ProtocolError(f"Protocol payload is missing fields: {', '.join(missing)}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ProtocolError("Unsupported schema version.")
    if payload["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported helper protocol version.")
    if payload["action"] not in (*ACTIONS, "unknown"):
        raise ProtocolError("Protocol payload contains an unknown action.")
    if not isinstance(payload["ok"], bool):
        raise ProtocolError("Protocol payload field 'ok' must be boolean.")
    if payload["ok"]:
        if "error" in payload:
            raise ProtocolError("Successful payloads must not contain an error field.")
    else:
        if not isinstance(payload.get("error"), str) or not payload["error"]:
            raise ProtocolError("Error payloads require a non-empty error field.")
        if not isinstance(payload.get("message"), str) or not payload["message"]:
            raise ProtocolError("Error payloads require a non-empty message field.")


__all__ = [
    "ACTIONS",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "RequestContext",
    "error_payload",
    "infer_action",
    "success_payload",
    "validate_payload",
]
