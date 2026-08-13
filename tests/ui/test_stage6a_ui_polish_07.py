from __future__ import annotations

import json
from pathlib import Path
import unittest

from pia_bazzite.models import Region
from pia_bazzite.region_names import (
    region_is_normal,
    region_matches_search,
    search_haystack,
)


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
ICONS = ROOT / "pia_bazzite" / "icons.py"
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage6AUiPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.icons = ICONS.read_text(encoding="utf-8")
        cls.options = OPTIONS.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    @staticmethod
    def _region(*, name: str, geo: bool) -> Region:
        return Region(
            region_id=name.casefold().replace(" ", "-"),
            name=name,
            meta_ip="198.51.100.1",
            wireguard_ip="198.51.100.2",
            wireguard_hostname="example.invalid",
            geo=geo,
            ping_ms=18.0,
        )

    def test_compact_main_is_50_pixels_narrower_but_log_width_is_unchanged(self) -> None:
        self.assertIn("COMPACT_SIZE = QSize(690, 510)", self.gui)
        self.assertIn("LOG_SIZE = QSize(760, 780)", self.gui)

    def test_german_tools_menu_is_now_extras_while_english_stays_tools(self) -> None:
        self.assertEqual(self.de["menu.tools"], "&Extras")
        self.assertEqual(self.en["menu.tools"], "&Tools")

    def test_virtual_marker_explains_physical_location_and_streaming_keeps_only_its_legend(self) -> None:
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
        self.assertIn("tr('region.streaming_tooltip')", self.gui)
        self.assertNotIn(
            "Für Streaming-Dienste optimiert",
            self.de["region.streaming_tooltip"],
        )

    def test_search_understands_normal_virtual_streaming_and_multiple_tokens(self) -> None:
        normal = self._region(name="DE Frankfurt", geo=False)
        virtual = self._region(name="Monaco", geo=True)
        streaming = self._region(name="Belgium Streaming Optimized", geo=False)

        self.assertTrue(region_is_normal(normal))
        self.assertFalse(region_is_normal(virtual))
        self.assertFalse(region_is_normal(streaming))

        self.assertTrue(region_matches_search(normal, "normal frankfurt"))
        self.assertTrue(region_matches_search(virtual, "virtuell monaco"))
        self.assertTrue(region_matches_search(virtual, "virtual monaco"))
        self.assertTrue(region_matches_search(streaming, "streaming belgien"))
        self.assertFalse(region_matches_search(normal, "streaming"))
        self.assertIn("virtuell", search_haystack(virtual))

    def test_filter_is_integrated_into_search_and_combines_with_text_search(self) -> None:
        self.assertIn("self.search_edit.addAction(", self.gui)
        self.assertIn("QLineEdit.ActionPosition.TrailingPosition", self.gui)
        for mode in (
            "REGION_FILTER_ALL",
            "REGION_FILTER_NORMAL",
            "REGION_FILTER_VIRTUAL",
            "REGION_FILTER_STREAMING",
        ):
            self.assertIn(mode, self.gui)
        self.assertIn("def _region_matches_filter", self.gui)
        self.assertIn("and region_matches_search(region, query)", self.gui)
        self.assertIn("self._favorite_snapshot_matches_filter(favorite)", self.gui)
        self.assertIn(
            "if not query and self._region_filter_mode == REGION_FILTER_ALL:",
            self.gui,
        )

    def test_filter_copy_is_bilingual_and_translation_sets_stay_equal(self) -> None:
        for key in (
            "connection.filter.all",
            "connection.filter.normal",
            "connection.filter.virtual",
            "connection.filter.streaming",
            "connection.filter.tooltip",
        ):
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertEqual(set(self.de), set(self.en))

    def test_action_icons_are_neutral_while_actual_favorites_keep_gold(self) -> None:
        # Main selector: Fastest is a neutral mode icon, favorites alone are gold.
        self.assertIn('self._region_marker_icon("⚡", accent=False)', self.gui)
        self.assertIn('star = "★" if favorite else "☆"', self.gui)
        self.assertIn("accent=favorite", self.gui)
        self.assertIn("QIcon.Mode.Selected", self.gui)
        self.assertIn('elif symbol == "☆":', self.gui)

        # Options: favorite status stays gold; Fastest and Off are neutral.
        self.assertIn('self._auto_connect_marker_icon("★", accent=True)', self.options)
        self.assertIn('self._auto_connect_marker_icon("⚡", accent=False)', self.options)
        self.assertIn("def _auto_connect_palette_icon", self.options)

        # Tray: Fastest is an icon rather than an emoji-glyph text marker and
        # Quit deliberately bypasses Plasma's commonly red semantic icon.
        self.assertIn('fastest_action.setIcon(tray_menu_icon("fastest"))', self.gui)
        self.assertNotIn('f"⚡ {tr(\'connection.fastest\')}"', self.gui)
        self.assertIn('"fastest": ()', self.icons)
        self.assertIn('"quit": ()', self.icons)


if __name__ == "__main__":
    unittest.main()
