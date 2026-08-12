from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
RESOURCE_DIR = ROOT / "pia_bazzite" / "resources" / "i18n"


class ServerFavoritesStage2BTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = GUI.read_text(encoding="utf-8")

    def _method(self, name: str, next_name: str) -> str:
        start = self.source.index(f"    def {name}(")
        end = self.source.index(f"    def {next_name}(", start)
        return self.source[start:end]

    def test_combo_intercepts_only_star_clicks_before_normal_selection(self) -> None:
        combo_start = self.source.index("class RegionComboBox(QComboBox):")
        combo_end = self.source.index("\n\n_CONNECTION_EVENT_LOG_KEYS", combo_start)
        combo = self.source[combo_start:combo_end]

        self.assertIn("favoriteToggled = Signal(str)", combo)
        self.assertIn("viewport().installEventFilter(self)", combo)
        self.assertIn("REGION_FAVORITE_STAR_HIT_WIDTH", combo)
        self.assertIn("QEvent.Type.MouseButtonPress", combo)
        self.assertIn("QEvent.Type.MouseButtonRelease", combo)
        self.assertIn("return True", combo)
        self.assertIn("self.favoriteToggled.emit(selected)", combo)
        self.assertIn("item.setEnabled(bool(available))", combo)

    def test_popup_always_opens_at_top_of_favorites_order(self) -> None:
        combo_start = self.source.index("class RegionComboBox(QComboBox):")
        combo_end = self.source.index("\n\n_CONNECTION_EVENT_LOG_KEYS", combo_start)
        combo = self.source[combo_start:combo_end]

        self.assertIn("QTimer.singleShot(0, self._prepare_popup)", combo)
        self.assertIn("def _prepare_popup(self) -> None:", combo)
        self.assertIn("self._limit_popup_height()", combo)
        self.assertIn("self.view().scrollToTop()", combo)
        self.assertNotIn("QTimer.singleShot(0, self._limit_popup_height)", combo)

    def test_main_window_wires_star_toggle_separately_from_selection(self) -> None:
        self.assertIn(
            "self.region_combo.favoriteToggled.connect(self._toggle_region_favorite)",
            self.source,
        )
        self.assertIn(
            "self.region_combo.currentIndexChanged.connect(self._selection_changed)",
            self.source,
        )

        toggle = self._method("_toggle_region_favorite", "_selection_changed")
        self.assertIn("self.region_favorites.add(region)", toggle)
        self.assertIn("self.region_favorites.remove(region_id)", toggle)
        self.assertNotIn("connect_region", toggle)
        self.assertNotIn("_selection_changed", toggle)

    def test_favorites_are_grouped_before_fastest_and_normal_regions(self) -> None:
        populate = self._method("_populate_region_combo", "_toggle_region_favorite")
        favorite_loop = populate.index("for region in favorite_regions:")
        missing_loop = populate.index("for favorite in missing_favorites:")
        fastest = populate.index("if not query:")
        normal_loop = populate.index("for region in normal_regions:")

        self.assertLess(favorite_loop, missing_loop)
        self.assertLess(missing_loop, fastest)
        self.assertLess(fastest, normal_loop)
        self.assertIn('star = "★" if favorite else "☆"', self.source)

    def test_favorite_and_fastest_markers_use_accent_icons(self) -> None:
        marker = self._method("_region_marker_icon", "_add_region_combo_item")
        add_item = self._method("_add_region_combo_item", "_first_selectable_region_index")
        populate = self._method("_populate_region_combo", "_toggle_region_favorite")

        self.assertIn('REGION_MARKER_ACCENT_COLOR = "#f4c542"', self.source)
        self.assertIn("QColor(REGION_MARKER_ACCENT_COLOR)", marker)
        self.assertIn("QPalette.ColorRole.Text", marker)
        self.assertIn('star = "★" if favorite else "☆"', add_item)
        self.assertIn("self._region_marker_icon(star, accent=favorite)", add_item)
        self.assertIn('self._region_marker_icon("⚡", accent=True)', populate)
        self.assertIn('if symbol == "⚡":', marker)
        self.assertIn("QPainterPath()", marker)
        self.assertIn("painter.fillPath(bolt, color)", marker)
        self.assertIn("self.region_combo.addItem(icon, text, region_id)", add_item)
        self.assertIn("self.region_combo.addItem(fastest_icon, fastest_text, FASTEST_ID)", populate)
        self.assertNotIn('addItem(f"⚡ ', populate)

    def test_only_missing_favorites_get_retained_unavailable_rows(self) -> None:
        populate = self._method("_populate_region_combo", "_toggle_region_favorite")
        self.assertIn("favorite.region_id not in current_ids", populate)
        self.assertIn("available=False", populate)
        self.assertIn('tr("favorites.unavailable_suffix")', populate)
        self.assertNotIn("normal_regions_missing", populate)

    def test_catalogued_ping_failure_remains_available(self) -> None:
        add_item = self._method("_add_region_combo_item", "_first_selectable_region_index")
        populate = self._method("_populate_region_combo", "_toggle_region_favorite")
        self.assertIn("self.region_combo.set_region_row_available(row, available)", add_item)
        self.assertGreaterEqual(populate.count("available=True"), 2)
        self.assertNotIn("ping_ms is None", populate)

    def test_unavailable_favorite_never_becomes_selected_connection_target(self) -> None:
        populate = self._method("_populate_region_combo", "_toggle_region_favorite")
        self.assertIn("REGION_FAVORITE_AVAILABLE_ROLE", populate)
        self.assertIn("target_index = -1", populate)
        self.assertIn("target_index = self._first_selectable_region_index()", populate)

    def test_successful_catalog_refresh_updates_only_favorite_snapshots(self) -> None:
        refresh = self._method("refresh_regions", "refresh_pings")
        self.assertIn("self.region_favorites.refresh_snapshots(self.regions)", refresh)
        self.assertIn("self.regions = list(result)", refresh)

    def test_limit_feedback_and_favorite_copy_exist_in_both_languages(self) -> None:
        en = json.loads((RESOURCE_DIR / "en.json").read_text(encoding="utf-8"))
        de = json.loads((RESOURCE_DIR / "de.json").read_text(encoding="utf-8"))
        keys = {
            "favorites.add_tooltip",
            "favorites.remove_tooltip",
            "favorites.unavailable_suffix",
            "favorites.unavailable_tooltip",
            "favorites.limit_title",
            "favorites.limit_message",
        }
        self.assertTrue(keys <= set(en))
        self.assertTrue(keys <= set(de))
        self.assertIn("{limit}", en["favorites.limit_message"])
        self.assertIn("{limit}", de["favorites.limit_message"])
        self.assertIn("not in the current PIA server list", en["favorites.unavailable_tooltip"])
        self.assertIn("nicht in der aktuellen PIA-Serverliste", de["favorites.unavailable_tooltip"])


if __name__ == "__main__":
    unittest.main()
