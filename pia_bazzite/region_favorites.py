from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Iterable, Protocol

from .models import Region


FAVORITE_REGIONS_KEY = "regions/favorites_v1"
FAVORITE_REGIONS_VERSION = 1
MAX_FAVORITE_REGIONS = 10


class SettingsLike(Protocol):
    def value(self, key: str, default: Any = None, *, type: type | None = None) -> Any:
        ...

    def setValue(self, key: str, value: Any) -> None:
        ...

    def sync(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class FavoriteRegion:
    """Persistent identity/label snapshot for one user-selected PIA region.

    ``name`` and ``geo`` are intentionally stored alongside ``region_id`` so a
    favorite can still be shown and removed if a later successful PIA server
    list no longer contains that region.  They are display fallbacks only; an
    unavailable favorite never carries stale endpoint data for connection use.
    """

    region_id: str
    name: str
    geo: bool = False

    @classmethod
    def from_region(cls, region: Region) -> "FavoriteRegion":
        region_id = _clean_region_id(region.region_id)
        if region_id is None:
            raise ValueError("Cannot favorite a region without a valid region_id.")
        return cls(
            region_id=region_id,
            name=_clean_name(region.name, fallback=region_id),
            geo=bool(region.geo),
        )


@dataclass(frozen=True, slots=True)
class FavoriteRegionAvailability:
    favorite: FavoriteRegion
    current_region: Region | None

    @property
    def available(self) -> bool:
        """Whether PIA's current successful region catalog still contains it.

        Availability is catalog membership, not latency reachability.  A
        current region with ``ping_ms is None`` is still available/selectable;
        only a region missing from the current catalog is unavailable.
        """

        return self.current_region is not None


class FavoriteAddResult(str, Enum):
    ADDED = "added"
    ALREADY_FAVORITE = "already_favorite"
    LIMIT_REACHED = "limit_reached"


class FavoriteRegionStore:
    """Persistent, user-owned PIA region favorites.

    The store never deletes a favorite merely because it disappears from a
    refreshed PIA region list.  Missing favorites continue counting toward the
    ten-item limit until the user explicitly removes them.
    """

    def __init__(self, settings: SettingsLike) -> None:
        self.settings = settings
        self._favorites = list(self._load())

    @property
    def count(self) -> int:
        return len(self._favorites)

    def all(self) -> tuple[FavoriteRegion, ...]:
        return tuple(self._favorites)

    def is_favorite(self, region_id: str) -> bool:
        cleaned = _clean_region_id(region_id)
        if cleaned is None:
            return False
        return any(item.region_id == cleaned for item in self._favorites)

    def add(self, region: Region) -> FavoriteAddResult:
        favorite = FavoriteRegion.from_region(region)
        if self.is_favorite(favorite.region_id):
            return FavoriteAddResult.ALREADY_FAVORITE
        if self.count >= MAX_FAVORITE_REGIONS:
            return FavoriteAddResult.LIMIT_REACHED
        self._favorites.append(favorite)
        self._persist()
        return FavoriteAddResult.ADDED

    def remove(self, region_id: str) -> bool:
        cleaned = _clean_region_id(region_id)
        if cleaned is None:
            return False
        updated = [item for item in self._favorites if item.region_id != cleaned]
        if len(updated) == len(self._favorites):
            return False
        self._favorites = updated
        self._persist()
        return True

    def availability(
        self,
        regions: Iterable[Region],
    ) -> tuple[FavoriteRegionAvailability, ...]:
        current_by_id = _current_regions_by_id(regions)
        return tuple(
            FavoriteRegionAvailability(
                favorite=favorite,
                current_region=current_by_id.get(favorite.region_id),
            )
            for favorite in self._favorites
        )

    def refresh_snapshots(self, regions: Iterable[Region]) -> bool:
        """Refresh fallback labels for favorites present in a current catalog.

        Missing favorites are deliberately retained unchanged.  This method is
        intended to run only after a successful PIA region-list load; callers
        should not interpret a network/load failure as a catalog containing
        zero regions.
        """

        current_by_id = _current_regions_by_id(regions)
        changed = False
        updated: list[FavoriteRegion] = []
        for favorite in self._favorites:
            current = current_by_id.get(favorite.region_id)
            if current is None:
                updated.append(favorite)
                continue
            refreshed = FavoriteRegion.from_region(current)
            updated.append(refreshed)
            if refreshed != favorite:
                changed = True

        if changed:
            self._favorites = updated
            self._persist()
        return changed

    def _load(self) -> tuple[FavoriteRegion, ...]:
        raw = self.settings.value(FAVORITE_REGIONS_KEY, "")
        if not isinstance(raw, str) or not raw.strip():
            return ()

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return ()
        if not isinstance(payload, dict) or payload.get("version") != FAVORITE_REGIONS_VERSION:
            return ()

        raw_favorites = payload.get("favorites", [])
        if not isinstance(raw_favorites, list):
            return ()

        favorites: list[FavoriteRegion] = []
        seen: set[str] = set()
        for item in raw_favorites:
            if len(favorites) >= MAX_FAVORITE_REGIONS:
                break
            if not isinstance(item, dict):
                continue
            region_id = _clean_region_id(item.get("region_id"))
            if region_id is None or region_id in seen:
                continue
            favorites.append(
                FavoriteRegion(
                    region_id=region_id,
                    name=_clean_name(item.get("name"), fallback=region_id),
                    geo=bool(item.get("geo", False)),
                )
            )
            seen.add(region_id)
        return tuple(favorites)

    def _persist(self) -> None:
        payload = {
            "version": FAVORITE_REGIONS_VERSION,
            "favorites": [
                {
                    "region_id": favorite.region_id,
                    "name": favorite.name,
                    "geo": favorite.geo,
                }
                for favorite in self._favorites
            ],
        }
        self.settings.setValue(
            FAVORITE_REGIONS_KEY,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        self.settings.sync()


def _current_regions_by_id(regions: Iterable[Region]) -> dict[str, Region]:
    current: dict[str, Region] = {}
    for region in regions:
        region_id = _clean_region_id(region.region_id)
        if region_id is not None and region_id not in current:
            current[region_id] = region
    return current


def _clean_region_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 256:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        return None
    return cleaned


def _clean_name(value: Any, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 512:
        return fallback
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        return fallback
    return cleaned


__all__ = [
    "FAVORITE_REGIONS_KEY",
    "FAVORITE_REGIONS_VERSION",
    "MAX_FAVORITE_REGIONS",
    "FavoriteAddResult",
    "FavoriteRegion",
    "FavoriteRegionAvailability",
    "FavoriteRegionStore",
]
