from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pia_bazzite.autostart import (
    AUTOSTART_ARGUMENT,
    AUTOSTART_FILENAME,
    autostart_enabled,
    current_autostart_command,
    render_autostart_desktop,
    set_autostart_enabled,
)


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"
GUI = ROOT / "pia_bazzite" / "gui.py"
ICONS = ROOT / "pia_bazzite" / "icons.py"
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
SINGLE_INSTANCE = ROOT / "pia_bazzite" / "single_instance.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage4CAutostartCoreTests(unittest.TestCase):
    def test_enable_writes_only_named_user_autostart_entry_and_disable_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "autostart" / AUTOSTART_FILENAME
            neighbor = target.parent / "other.desktop"
            target.parent.mkdir(parents=True)
            neighbor.write_text("leave me alone", encoding="utf-8")

            set_autostart_enabled(
                True,
                path=target,
                command=("/home/Test User/PIA Bazzite.AppImage", AUTOSTART_ARGUMENT),
            )
            self.assertTrue(target.is_file())
            self.assertTrue(autostart_enabled(target))
            text = target.read_text(encoding="utf-8")
            self.assertIn("X-PIA-Bazzite-Autostart=true", text)
            self.assertIn('Exec="/home/Test User/PIA Bazzite.AppImage" "--autostart"', text)
            self.assertEqual(neighbor.read_text(encoding="utf-8"), "leave me alone")

            set_autostart_enabled(False, path=target)
            self.assertFalse(target.exists())
            self.assertEqual(neighbor.read_text(encoding="utf-8"), "leave me alone")

    def test_disabled_desktop_entry_is_not_reported_as_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / AUTOSTART_FILENAME
            target.write_text("[Desktop Entry]\nHidden=true\n", encoding="utf-8")
            self.assertFalse(autostart_enabled(target))
            target.write_text(
                "[Desktop Entry]\nX-GNOME-Autostart-enabled=false\n",
                encoding="utf-8",
            )
            self.assertFalse(autostart_enabled(target))

    def test_exec_quoting_preserves_literal_percent_and_does_not_use_shell(self) -> None:
        text = render_autostart_desktop(
            ("/home/A User/PIA%20.AppImage", AUTOSTART_ARGUMENT)
        )
        self.assertIn('Exec="/home/A User/PIA%%20.AppImage" "--autostart"', text)
        self.assertNotIn("sh -c", text)
        self.assertNotIn("bash -c", text)

    def test_appimage_runtime_uses_original_appimage_path_not_mount_executable(self) -> None:
        with patch.dict(os.environ, {"APPIMAGE": "/home/tester/Applications/PIA Bazzite.AppImage"}):
            self.assertEqual(
                current_autostart_command(),
                ("/home/tester/Applications/PIA Bazzite.AppImage", AUTOSTART_ARGUMENT),
            )


class Stage4CAutostartUiStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.icons = ICONS.read_text(encoding="utf-8")
        cls.options = OPTIONS.read_text(encoding="utf-8")
        cls.single_instance = SINGLE_INSTANCE.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_options_exposes_real_xdg_autostart_checkbox_without_qsettings_shadow(self) -> None:
        self.assertIn('self.autostart_checkbox = QCheckBox(tr("options.autostart_enabled"))', self.options)
        self.assertIn("self.autostart_checkbox.setChecked(autostart_enabled())", self.options)
        self.assertIn("autostart_enabled=self.autostart_checkbox.isChecked()", self.options)
        self.assertIn("current_autostart_enabled = autostart_enabled()", self.gui)
        self.assertIn("self.change_autostart_enabled(values.autostart_enabled)", self.gui)
        self.assertIn("set_autostart_enabled(enabled)", self.gui)
        self.assertNotIn('settings.setValue("ui/autostart', self.options + self.gui)

    def test_autostart_launch_stays_hidden_only_when_tray_is_really_enabled(self) -> None:
        self.assertIn("autostart_launch = AUTOSTART_ARGUMENT in sys.argv[1:]", self.main)
        self.assertIn("qt_argv = [arg for arg in sys.argv if arg != AUTOSTART_ARGUMENT]", self.main)
        self.assertIn("instance.claim(activate_existing=not autostart_launch)", self.main)
        self.assertIn(
            'if not autostart_launch or not bool_value(settings, "ui/tray_enabled", True):',
            self.main,
        )
        self.assertIn("window.show()", self.main)
        self.assertIn("def claim(self, *, activate_existing: bool = True)", self.single_instance)
        self.assertIn("request_activation=activate_existing", self.single_instance)

    def test_top_level_tray_actions_have_icons_but_status_row_does_not(self) -> None:
        start = self.gui.index("    def _rebuild_tray_menu")
        end = self.gui.index("    def _add_tray_favorites_menu", start)
        tray = self.gui[start:end]
        for role in ("connect", "disconnect", "locations", "show", "quit"):
            self.assertIn(f'tray_menu_icon("{role}")', tray)
        status = tray[tray.index("status_action = QAction(tray_status_text, menu)"):]
        status = status[: status.index("if connected:")]
        self.assertNotIn("status_action.setIcon", status)

    def test_favorites_parent_has_icon_and_child_stars_are_removed(self) -> None:
        start = self.gui.index("    def _add_tray_favorites_menu")
        end = self.gui.index("    def _tray_setting_changed", start)
        helper = self.gui[start:end]
        self.assertIn('favorites_menu.setIcon(tray_menu_icon("favorites"))', helper)
        self.assertNotIn('action.setIcon(self._region_marker_icon("★", accent=True))', helper)

    def test_tray_icons_prefer_desktop_theme_and_have_vector_fallbacks(self) -> None:
        for role in ("connect", "disconnect", "locations", "favorites", "show", "quit"):
            self.assertIn(f'"{role}"', self.icons)
        self.assertIn("QIcon.fromTheme(name)", self.icons)
        self.assertIn("_tray_menu_fallback_icon", self.icons)

    def test_bilingual_autostart_copy_and_error_reporting_exist(self) -> None:
        for key in (
            "options.autostart_enabled",
            "options.autostart_tooltip",
            "log.autostart.enabled",
            "log.autostart.disabled",
            "log.autostart.failed",
            "error.autostart.title",
            "error.autostart.message",
        ):
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertEqual(set(self.de), set(self.en))
        self.assertIn("Anmeldung", self.de["options.autostart_enabled"])
        self.assertIn("login", self.en["options.autostart_enabled"].lower())


if __name__ == "__main__":
    unittest.main()
