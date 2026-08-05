from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Region:
    region_id: str
    name: str
    meta_ip: str
    wireguard_ip: str
    wireguard_hostname: str
    geo: bool = False
    ping_ms: float | None = None

    def with_ping(self, ping_ms: float | None) -> "Region":
        return replace(self, ping_ms=ping_ms)


@dataclass(frozen=True, slots=True)
class PublicNetworkInfo:
    ip_address: str
    country_code: str


@dataclass(frozen=True, slots=True)
class SystemCheck:
    key: str
    ok: bool
    detail: str
    required: bool = True
