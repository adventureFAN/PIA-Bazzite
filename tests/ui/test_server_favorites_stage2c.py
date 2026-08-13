from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
RESOURCE_DIR = ROOT / "pia_bazzite" / "resources" / "i18n"


class ServerFavoritesStage2CTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = GUI.read_text(encoding="utf-8")

    def _method(self, name: str, next_name: str) -> str:
        start = self.source.index(f"    def {name}(")
        end = self.source.index(f"    def {next_name}(", start)
        return self.source[start:end]

    def test_favorites_are_a_root_level_sibling_submenu(self) -> None:
        helper = self._method("_add_tray_favorites_menu", "_tray_setting_changed")
        tray = self._method("_rebuild_tray_menu", "_add_tray_favorites_menu")

        self.assertIn('favorites_menu = menu.addMenu(tr("tray.favorites"))', helper)
        self.assertNotIn("locations_menu.addMenu", helper)
        self.assertIn("self._add_tray_favorites_menu(\n            menu,", tray)
        self.assertNotIn("_add_tray_favorite_actions(locations_menu)", tray)

    def test_no_saved_favorites_means_no_favorites_menu(self) -> None:
        helper = self._method("_add_tray_favorites_menu", "_tray_setting_changed")
        self.assertIn("favorites = self.region_favorites.all()", helper)
        self.assertIn("if not favorites:", helper)
        self.assertIn("return None", helper)
        self.assertLess(
            helper.index("if not favorites:"),
            helper.index('menu.addMenu(tr("tray.favorites"))'),
        )

    def test_favorites_menu_sits_after_connect_switch_and_before_bottom_separator(self) -> None:
        tray = self._method("_rebuild_tray_menu", "_add_tray_favorites_menu")
        locations = tray.index("locations_menu = menu.addMenu(")
        favorites = tray.index("self._add_tray_favorites_menu(")
        bottom_separator = tray.index("        menu.addSeparator()", favorites)
        show = tray.index('show_action = QAction(tr("tray.show"), menu)', favorites)

        self.assertLess(locations, favorites)
        self.assertLess(favorites, bottom_separator)
        self.assertLess(bottom_separator, show)

    def test_favorites_root_has_menu_icon_and_child_rows_stay_clean(self) -> None:
        helper = self._method("_add_tray_favorites_menu", "_tray_setting_changed")
        self.assertIn('favorites_menu.setIcon(tray_menu_icon("favorites"))', helper)
        self.assertNotIn('action.setIcon(self._region_marker_icon("★", accent=True))', helper)

    def test_available_favorites_use_current_catalog_and_existing_connect_path(self) -> None:
        helper = self._method("_add_tray_favorites_menu", "_tray_setting_changed")

        self.assertIn("current_by_id = {region.region_id: region for region in self.regions}", helper)
        self.assertIn("favorite_ids = {favorite.region_id for favorite in favorites}", helper)
        self.assertIn("region for region in self.regions if region.region_id in favorite_ids", helper)
        self.assertIn("self.connect_region(selected)", helper)
        self.assertNotIn("network_manager.connect", helper)
        self.assertNotIn("create_wireguard_config", helper)

    def test_missing_tray_favorites_are_visible_but_disabled(self) -> None:
        helper = self._method("_add_tray_favorites_menu", "_tray_setting_changed")

        self.assertIn("favorite.region_id not in current_by_id", helper)
        self.assertIn("self._favorite_snapshot_display_name(favorite)", helper)
        self.assertIn('tr("favorites.unavailable_suffix")', helper)
        self.assertIn("action.setEnabled(False)", helper)
        missing_block = helper[helper.index("for favorite in missing_favorites:"):]
        self.assertNotIn("connect_region", missing_block)

    def test_normal_connect_switch_menu_remains_the_existing_server_menu(self) -> None:
        tray = self._method("_rebuild_tray_menu", "_add_tray_favorites_menu")
        fastest = tray.index("fastest = self._selected_fastest_region()")
        reachable = tray.index("reachable = [")
        full_list = tray.index('full_list_action = QAction(tr("tray.full_list"), locations_menu)')

        self.assertLess(fastest, reachable)
        self.assertLess(reachable, full_list)
        self.assertIn('fastest_action.setIcon(tray_menu_icon("fastest"))', tray)
        self.assertNotIn('f"⚡ {tr(\'connection.fastest\')}"', tray)
        reachable_block = tray[reachable:tray.index("for region in reachable:", reachable)]
        self.assertNotIn("favorite_ids", reachable_block)
        self.assertIn("[:20]", reachable_block)

    def test_tray_rebuilds_immediately_after_main_favorite_toggle(self) -> None:
        toggle = self._method("_toggle_region_favorite", "_selection_changed")
        self.assertIn("self._populate_region_combo()", toggle)
        self.assertIn("self._rebuild_tray_menu()", toggle)
        self.assertLess(
            toggle.index("self._populate_region_combo()"),
            toggle.index("self._rebuild_tray_menu()"),
        )

    def test_favorites_menu_has_de_and_en_translation(self) -> None:
        en = json.loads((RESOURCE_DIR / "en.json").read_text(encoding="utf-8"))
        de = json.loads((RESOURCE_DIR / "de.json").read_text(encoding="utf-8"))
        self.assertEqual(en["tray.favorites"], "Favorites")
        self.assertEqual(de["tray.favorites"], "Favoriten")

    def test_favorites_parent_obeys_existing_tray_safety_gates(self) -> None:
        tray = self._method("_rebuild_tray_menu", "_add_tray_favorites_menu")
        call = tray[tray.index("self._add_tray_favorites_menu("):]
        self.assertIn("network_state_known", call)
        self.assertIn("not self._connection_busy", call)
        self.assertIn("not disconnected_lock", call)
        helper = self._method("_add_tray_favorites_menu", "_tray_setting_changed")
        self.assertIn("favorites_menu.setEnabled(enabled)", helper)


if __name__ == "__main__":
    unittest.main()
