from __future__ import annotations

import json
from pathlib import Path
import unittest

from pia_bazzite.auto_connect import (
    AUTO_CONNECT_FASTEST,
    AUTO_CONNECT_LAST,
    AUTO_CONNECT_OFF,
    auto_connect_region_id,
    normalize_auto_connect_target,
    region_auto_connect_target,
)


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage4AAutoConnectOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.options = OPTIONS.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_target_encoding_is_safe_and_defaults_off(self) -> None:
        self.assertEqual(normalize_auto_connect_target(None), AUTO_CONNECT_OFF)
        self.assertEqual(normalize_auto_connect_target("garbage"), AUTO_CONNECT_OFF)
        self.assertEqual(normalize_auto_connect_target(" last "), AUTO_CONNECT_LAST)
        self.assertEqual(normalize_auto_connect_target("fastest"), AUTO_CONNECT_FASTEST)
        target = region_auto_connect_target("nl-amsterdam")
        self.assertEqual(target, "region:nl-amsterdam")
        self.assertEqual(auto_connect_region_id(target), "nl-amsterdam")
        self.assertIsNone(auto_connect_region_id(AUTO_CONNECT_LAST))

    def test_stage4a_is_preference_only_not_startup_behavior(self) -> None:
        self.assertIn("def change_auto_connect_target", self.gui)
        start = self.gui.index("    def change_auto_connect_target")
        end = self.gui.index("    def change_public_network_provider", start)
        block = self.gui[start:end]
        self.assertIn("self.settings.setValue(AUTO_CONNECT_KEY, normalized)", block)
        self.assertIn("self.settings.sync()", block)
        self.assertNotIn("connect_region", block)
        self.assertNotIn("toggle_connection", block)

    def test_options_are_one_compact_selector_with_off_last_favorites_fastest_and_regions(self) -> None:
        self.assertIn("self.auto_connect_combo = AutoConnectComboBox()", self.options)
        self.assertIn('tr("options.auto_connect.off")', self.options)
        self.assertIn('tr("options.auto_connect.last")', self.options)
        self.assertIn('tr("options.auto_connect.favorites")', self.options)
        self.assertIn("AUTO_CONNECT_FASTEST", self.options)
        self.assertIn("available_favorites.sort(key=self._region_ping_sort_key)", self.options)
        self.assertIn("normal_regions.sort(key=self._region_ping_sort_key)", self.options)
        self.assertIn("compact_region_display_name(region, language())", self.options)

    def test_auto_connect_popup_is_bounded_and_scrollable(self) -> None:
        self.assertIn("AUTO_CONNECT_POPUP_VISIBLE_ITEMS = 20", self.options)
        self.assertIn("class AutoConnectComboBox(QComboBox)", self.options)
        self.assertIn("def _limit_popup_height", self.options)
        self.assertIn("view.setMaximumHeight(height)", self.options)
        self.assertIn("popup.setMaximumHeight(height)", self.options)

    def test_favorite_and_fastest_entries_use_gold_icons(self) -> None:
        self.assertIn('AUTO_CONNECT_ACCENT_COLOR = "#f4c542"', self.options)
        self.assertIn('self._auto_connect_marker_icon("★")', self.options)
        self.assertIn('self._auto_connect_marker_icon("⚡")', self.options)
        self.assertIn("QPainterPath()", self.options)
        self.assertNotIn('f"★ {compact_region_display_name', self.options)
        self.assertNotIn('f"⚡ {tr(', self.options)

    def test_auto_connect_quickinfo_has_paragraph_break(self) -> None:
        self.assertIn("\n\n", self.de["options.auto_connect_tooltip"])
        self.assertIn("\n\n", self.en["options.auto_connect_tooltip"])

    def test_fixed_targets_store_only_region_identity(self) -> None:
        self.assertIn("region_auto_connect_target(region.region_id)", self.options)
        self.assertNotIn("wireguard_ip", self.options)
        self.assertNotIn("wireguard_hostname", self.options)
        self.assertNotIn("meta_ip", self.options)

    def test_missing_saved_fixed_target_is_visible_but_disabled(self) -> None:
        self.assertIn("saved_region_id = auto_connect_region_id(saved_target)", self.options)
        self.assertIn('tr("options.auto_connect.unavailable", region=fallback_name)', self.options)
        self.assertIn("self._set_combo_item_enabled(combo, combo.count() - 1, False)", self.options)

    def test_gui_passes_live_catalog_and_favorites_to_options(self) -> None:
        self.assertIn("regions=self.regions", self.gui)
        self.assertIn("favorites=self.region_favorites.all()", self.gui)
        self.assertIn("values.auto_connect_target != current_auto_connect_target", self.gui)
        self.assertIn("self.change_auto_connect_target(values.auto_connect_target)", self.gui)

    def test_bilingual_labels_and_parity(self) -> None:
        for key in (
            "options.auto_connect",
            "options.auto_connect_tooltip",
            "options.auto_connect.off",
            "options.auto_connect.last",
            "options.auto_connect.favorites",
            "options.auto_connect.unavailable",
        ):
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertEqual(self.de["options.auto_connect"], "Automatisch verbinden:")
        self.assertEqual(self.en["options.auto_connect"], "Connect automatically:")
        self.assertEqual(set(self.de), set(self.en))


if __name__ == "__main__":
    unittest.main()
