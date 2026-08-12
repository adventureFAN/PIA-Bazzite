from __future__ import annotations

import json
import unittest

from pia_bazzite.models import Region
from pia_bazzite.region_favorites import (
    FAVORITE_REGIONS_KEY,
    MAX_FAVORITE_REGIONS,
    FavoriteAddResult,
    FavoriteRegionStore,
)


class FakeSettings:
    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.values = dict(initial or {})
        self.sync_count = 0

    def value(self, key: str, default: object = None, *, type: type | None = None) -> object:
        value = self.values.get(key, default)
        return type(value) if type is not None else value

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.sync_count += 1


def region(
    region_id: str,
    name: str | None = None,
    *,
    geo: bool = False,
    ping_ms: float | None = 20.0,
) -> Region:
    return Region(
        region_id=region_id,
        name=name or region_id,
        meta_ip="198.51.100.10",
        wireguard_ip="198.51.100.11",
        wireguard_hostname="example",
        geo=geo,
        ping_ms=ping_ms,
    )


class FavoriteRegionStoreTests(unittest.TestCase):
    def test_starts_empty_without_writing_settings(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)

        self.assertEqual(store.count, 0)
        self.assertEqual(store.all(), ())
        self.assertEqual(settings.sync_count, 0)

    def test_add_persists_identity_and_display_fallback(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)

        result = store.add(region("de-frankfurt", "DE Frankfurt", geo=True))

        self.assertEqual(result, FavoriteAddResult.ADDED)
        self.assertTrue(store.is_favorite("de-frankfurt"))
        self.assertEqual(store.count, 1)
        self.assertEqual(settings.sync_count, 1)

        reloaded = FavoriteRegionStore(settings)
        favorite = reloaded.all()[0]
        self.assertEqual(favorite.region_id, "de-frankfurt")
        self.assertEqual(favorite.name, "DE Frankfurt")
        self.assertTrue(favorite.geo)

    def test_duplicate_does_not_consume_another_slot_or_rewrite(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        self.assertEqual(store.add(region("nl-amsterdam")), FavoriteAddResult.ADDED)
        sync_count = settings.sync_count

        result = store.add(region("nl-amsterdam", "Renamed in duplicate add"))

        self.assertEqual(result, FavoriteAddResult.ALREADY_FAVORITE)
        self.assertEqual(store.count, 1)
        self.assertEqual(settings.sync_count, sync_count)

    def test_limit_is_ten_and_eleventh_favorite_is_rejected(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        for index in range(MAX_FAVORITE_REGIONS):
            self.assertEqual(
                store.add(region(f"region-{index}")),
                FavoriteAddResult.ADDED,
            )

        result = store.add(region("region-10"))

        self.assertEqual(result, FavoriteAddResult.LIMIT_REACHED)
        self.assertEqual(store.count, MAX_FAVORITE_REGIONS)
        self.assertFalse(store.is_favorite("region-10"))

    def test_missing_favorite_is_retained_and_counts_toward_limit(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        for index in range(MAX_FAVORITE_REGIONS):
            store.add(region(f"region-{index}"))

        availability = store.availability([region("region-0")])

        self.assertTrue(availability[0].available)
        self.assertFalse(availability[1].available)
        self.assertEqual(store.count, MAX_FAVORITE_REGIONS)
        self.assertEqual(
            store.add(region("replacement")),
            FavoriteAddResult.LIMIT_REACHED,
        )

        reloaded = FavoriteRegionStore(settings)
        self.assertTrue(reloaded.is_favorite("region-9"))

    def test_ping_failure_does_not_make_catalogued_favorite_unavailable(self) -> None:
        store = FavoriteRegionStore(FakeSettings())
        store.add(region("se-stockholm", ping_ms=12.0))

        availability = store.availability([region("se-stockholm", ping_ms=None)])

        self.assertTrue(availability[0].available)
        self.assertIsNone(availability[0].current_region.ping_ms)

    def test_refresh_updates_snapshot_but_never_deletes_missing_favorite(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        store.add(region("de-frankfurt", "Old Frankfurt"))
        store.add(region("legacy-region", "Legacy location", geo=True))
        sync_count = settings.sync_count

        changed = store.refresh_snapshots(
            [region("de-frankfurt", "DE Frankfurt", geo=True)]
        )

        self.assertTrue(changed)
        self.assertEqual(settings.sync_count, sync_count + 1)
        favorites = store.all()
        self.assertEqual(favorites[0].name, "DE Frankfurt")
        self.assertTrue(favorites[0].geo)
        self.assertEqual(favorites[1].region_id, "legacy-region")
        self.assertEqual(favorites[1].name, "Legacy location")
        self.assertTrue(favorites[1].geo)

    def test_refresh_with_no_matching_regions_keeps_everything_and_does_not_write(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        store.add(region("legacy-region", "Legacy location"))
        sync_count = settings.sync_count

        changed = store.refresh_snapshots([])

        self.assertFalse(changed)
        self.assertEqual(store.count, 1)
        self.assertEqual(settings.sync_count, sync_count)

    def test_user_can_remove_unavailable_favorite_and_free_slot(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        for index in range(MAX_FAVORITE_REGIONS):
            store.add(region(f"region-{index}"))

        availability = store.availability([])
        self.assertTrue(all(not item.available for item in availability))

        self.assertTrue(store.remove("region-4"))
        self.assertEqual(store.count, MAX_FAVORITE_REGIONS - 1)
        self.assertEqual(store.add(region("new-region")), FavoriteAddResult.ADDED)
        self.assertTrue(store.is_favorite("new-region"))

    def test_remove_unknown_or_invalid_id_is_noop(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        store.add(region("de-frankfurt"))
        sync_count = settings.sync_count

        self.assertFalse(store.remove("not-a-favorite"))
        self.assertFalse(store.remove("\n"))
        self.assertEqual(store.count, 1)
        self.assertEqual(settings.sync_count, sync_count)

    def test_malformed_settings_fail_closed_to_empty_favorites(self) -> None:
        settings = FakeSettings({FAVORITE_REGIONS_KEY: "not-json"})
        self.assertEqual(FavoriteRegionStore(settings).all(), ())

        wrong_version = json.dumps({"version": 99, "favorites": []})
        settings = FakeSettings({FAVORITE_REGIONS_KEY: wrong_version})
        self.assertEqual(FavoriteRegionStore(settings).all(), ())

    def test_loading_filters_duplicates_invalid_entries_and_caps_at_ten(self) -> None:
        raw_items = [
            {"region_id": "same", "name": "First", "geo": False},
            {"region_id": "same", "name": "Duplicate", "geo": True},
            {"region_id": "\n", "name": "Invalid", "geo": False},
        ]
        raw_items.extend(
            {"region_id": f"region-{index}", "name": f"Region {index}", "geo": False}
            for index in range(20)
        )
        settings = FakeSettings(
            {
                FAVORITE_REGIONS_KEY: json.dumps(
                    {"version": 1, "favorites": raw_items}
                )
            }
        )

        store = FavoriteRegionStore(settings)

        self.assertEqual(store.count, MAX_FAVORITE_REGIONS)
        ids = [favorite.region_id for favorite in store.all()]
        self.assertEqual(ids.count("same"), 1)
        self.assertNotIn("\n", ids)

    def test_persisted_payload_contains_no_endpoint_or_ping_data(self) -> None:
        settings = FakeSettings()
        store = FavoriteRegionStore(settings)
        store.add(region("de-frankfurt", "DE Frankfurt", ping_ms=9.0))

        payload = json.loads(str(settings.values[FAVORITE_REGIONS_KEY]))
        serialized = json.dumps(payload)

        self.assertIn("region_id", serialized)
        self.assertIn("name", serialized)
        self.assertIn("geo", serialized)
        self.assertNotIn("meta_ip", serialized)
        self.assertNotIn("wireguard_ip", serialized)
        self.assertNotIn("wireguard_hostname", serialized)
        self.assertNotIn("ping_ms", serialized)


if __name__ == "__main__":
    unittest.main()
