from __future__ import annotations

from typing import Any


AUTO_CONNECT_KEY = "connection/auto_connect_target"
AUTO_CONNECT_OFF = "off"
AUTO_CONNECT_LAST = "last"
AUTO_CONNECT_FASTEST = "fastest"
AUTO_CONNECT_REGION_PREFIX = "region:"


def region_auto_connect_target(region_id: str) -> str:
    cleaned = _clean_region_id(region_id)
    if cleaned is None:
        raise ValueError("Auto-connect region_id must be a non-empty safe string.")
    return f"{AUTO_CONNECT_REGION_PREFIX}{cleaned}"


def auto_connect_region_id(target: object) -> str | None:
    normalized = normalize_auto_connect_target(target)
    if not normalized.startswith(AUTO_CONNECT_REGION_PREFIX):
        return None
    return normalized[len(AUTO_CONNECT_REGION_PREFIX):]


def normalize_auto_connect_target(value: Any) -> str:
    if not isinstance(value, str):
        return AUTO_CONNECT_OFF
    cleaned = value.strip()
    if cleaned in {AUTO_CONNECT_OFF, AUTO_CONNECT_LAST, AUTO_CONNECT_FASTEST}:
        return cleaned
    if cleaned.startswith(AUTO_CONNECT_REGION_PREFIX):
        region_id = _clean_region_id(cleaned[len(AUTO_CONNECT_REGION_PREFIX):])
        if region_id is not None:
            return f"{AUTO_CONNECT_REGION_PREFIX}{region_id}"
    return AUTO_CONNECT_OFF


def _clean_region_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 256:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        return None
    return cleaned


def resolve_auto_connect_region_id(
    target: object,
    *,
    last_selected_region_id: str,
    fastest_region_id: str | None,
    fastest_selection_id: str,
) -> str | None:
    """Resolve an auto-connect preference to one concrete region identity.

    The helper never invents a fallback for a missing fixed/last region.  Only
    the explicit fastest choice (or a last selection that itself was the
    fastest pseudo-entry) resolves dynamically.
    """

    normalized = normalize_auto_connect_target(target)
    if normalized == AUTO_CONNECT_OFF:
        return None
    if normalized == AUTO_CONNECT_FASTEST:
        return fastest_region_id
    if normalized == AUTO_CONNECT_LAST:
        selected = str(last_selected_region_id or "").strip()
        if not selected:
            return None
        if selected == fastest_selection_id:
            return fastest_region_id
        return selected
    return auto_connect_region_id(normalized)
