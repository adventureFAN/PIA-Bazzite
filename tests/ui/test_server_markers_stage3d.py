from __future__ import annotations

import json
from pathlib import Path
import unittest

from pia_bazzite.models import Region
from pia_bazzite.region_names import (
    REGION_STREAMING_MARKER,
    REGION_VIRTUAL_MARKER,
    compact_region_display_name,
    region_display_name,
)


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class ServerMarkersStage3DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    @staticmethod
    def _region(*, name: str, geo: bool, ping: float | None = 18.0) -> Region:
        return Region(
            region_id="test",
            name=name,
            meta_ip="198.51.100.1",
            wireguard_ip="198.51.100.2",
            wireguard_hostname="example.invalid",
            geo=geo,
            ping_ms=ping,
        )

    def test_compact_server_list_uses_neutral_virtual_and_streaming_markers(self) -> None:
        region = self._region(name="Nigeria Streaming Optimized", geo=True)
        label = compact_region_display_name(region, "de")
        self.assertIn(REGION_VIRTUAL_MARKER, label)
        self.assertIn(REGION_STREAMING_MARKER, label)
        self.assertNotIn("virtueller Standort", label)
        self.assertNotIn("Streaming-optimiert", label)
        self.assertTrue(label.startswith("Nigeria "))
        self.assertTrue(label.endswith("· 18 ms"))

    def test_virtual_marker_is_filled_neutral_circle(self) -> None:
        self.assertEqual(REGION_VIRTUAL_MARKER, "●")

    def test_individual_markers_are_only_shown_when_applicable(self) -> None:
        virtual = compact_region_display_name(
            self._region(name="Monaco", geo=True), "de"
        )
        streaming = compact_region_display_name(
            self._region(name="Belgium Streaming Optimized", geo=False), "en"
        )
        normal = compact_region_display_name(
            self._region(name="Belgium", geo=False), "en"
        )
        self.assertIn(REGION_VIRTUAL_MARKER, virtual)
        self.assertNotIn(REGION_STREAMING_MARKER, virtual)
        self.assertIn(REGION_STREAMING_MARKER, streaming)
        self.assertNotIn(REGION_VIRTUAL_MARKER, streaming)
        self.assertNotIn(REGION_VIRTUAL_MARKER, normal)
        self.assertNotIn(REGION_STREAMING_MARKER, normal)

    def test_verbose_names_are_preserved_for_non_list_surfaces(self) -> None:
        region = self._region(name="Nigeria Streaming Optimized", geo=True)
        verbose = region_display_name(region, "de")
        self.assertIn("Streaming-optimiert", verbose)
        self.assertIn("virtueller Standort", verbose)

    def test_combo_rows_receive_marker_specific_quickinfo(self) -> None:
        self.assertIn("def _region_marker_tooltip_lines(", self.gui)
        self.assertIn("tr('region.virtual_tooltip')", self.gui)
        self.assertIn("tr('region.streaming_tooltip')", self.gui)
        self.assertIn("Qt.ItemDataRole.ToolTipRole", self.gui)
        self.assertIn("tooltip_lines = list(marker_lines)", self.gui)
        self.assertNotIn("favorites.add_tooltip", self.gui)
        self.assertNotIn("favorites.remove_tooltip", self.gui)
        self.assertIn("virtual=region.geo", self.gui)
        self.assertIn("streaming=region_is_streaming(region)", self.gui)

    def test_missing_favorite_keeps_snapshot_markers_and_safe_unavailable_state(self) -> None:
        start = self.gui.index("    def _favorite_snapshot_display_name")
        end = self.gui.index("    def _region_marker_icon", start)
        block = self.gui[start:end]
        self.assertIn("STREAMING_NAME_SUFFIX", block)
        self.assertIn("REGION_VIRTUAL_MARKER", block)
        self.assertIn("REGION_STREAMING_MARKER", block)

        populate_start = self.gui.index("    def _populate_region_combo")
        populate_end = self.gui.index("    def _toggle_region_favorite", populate_start)
        populate = self.gui[populate_start:populate_end]
        self.assertIn("available=False", populate)
        self.assertIn("virtual=favorite.geo", populate)
        self.assertIn("streaming=favorite_streaming", populate)

    def test_tray_location_and_favorites_use_compact_labels(self) -> None:
        tray_start = self.gui.index("        if fastest is not None:")
        tray_end = self.gui.index("        full_list_action = QAction", tray_start)
        tray_block = self.gui[tray_start:tray_end]
        self.assertIn("compact_region_display_name(region, language())", tray_block)

        favorites_start = self.gui.index("    def _add_tray_favorites_menu")
        favorites_end = self.gui.index(
            "    def _tray_setting_changed",
            favorites_start,
        )
        favorites_block = self.gui[favorites_start:favorites_end]
        self.assertIn(
            "compact_region_display_name(region, language())",
            favorites_block,
        )

    def test_tray_status_row_has_no_redundant_status_dot(self) -> None:
        self.assertNotIn("status_action.setIcon(status_dot_icon", self.gui)

    def test_marker_quickinfo_is_bilingual_and_key_sets_stay_equal(self) -> None:
        self.assertEqual(
            self.de["region.virtual_tooltip"],
            "Virtueller Standort\nDer Server befindet sich physisch in einem anderen Land.",
        )
        self.assertEqual(
            self.en["region.virtual_tooltip"],
            "Virtual location\nThe server is physically located in another country.",
        )
        self.assertEqual(
            self.de["region.streaming_tooltip"],
            "Streaming-optimierter Standort",
        )
        self.assertEqual(
            self.en["region.streaming_tooltip"],
            "Streaming-optimized location",
        )
        self.assertEqual(set(self.de), set(self.en))


if __name__ == "__main__":
    unittest.main()
