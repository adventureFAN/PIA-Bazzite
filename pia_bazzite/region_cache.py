from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Region
from .settings import cache_dir


CACHE_FILE = cache_dir() / "regions.json"


def save_regions(regions: list[Region]) -> None:
    payload = {
        "version": 1,
        "regions": [
            {
                "region_id": region.region_id,
                "name": region.name,
                "meta_ip": region.meta_ip,
                "wireguard_ip": region.wireguard_ip,
                "wireguard_hostname": region.wireguard_hostname,
                "geo": region.geo,
                "ping_ms": region.ping_ms,
            }
            for region in regions
        ],
    }
    temporary = CACHE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(CACHE_FILE)


def load_regions() -> list[Region]:
    if not CACHE_FILE.is_file():
        return []
    try:
        payload: dict[str, Any] = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            return []
        regions = [
            Region(
                region_id=str(item["region_id"]),
                name=str(item["name"]),
                meta_ip=str(item["meta_ip"]),
                wireguard_ip=str(item["wireguard_ip"]),
                wireguard_hostname=str(item["wireguard_hostname"]),
                geo=bool(item.get("geo", False)),
                ping_ms=(
                    float(item["ping_ms"])
                    if item.get("ping_ms") is not None
                    else None
                ),
            )
            for item in payload.get("regions", [])
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return []
    return regions
