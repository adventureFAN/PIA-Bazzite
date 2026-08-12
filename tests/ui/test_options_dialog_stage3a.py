from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage3AOptionsDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gui = GUI.read_text(encoding="utf-8")
        self.options = OPTIONS.read_text(encoding="utf-8")
        self.de = json.loads(DE.read_text(encoding="utf-8"))
        self.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_tools_menu_keeps_immediate_actions_and_opens_options_dialog(self) -> None:
        menu = self.gui[
            self.gui.index("    def _create_menu_bar") :
            self.gui.index("    def _create_main_ui")
        ]
        self.assertIn("self.options_menu.addAction(self.kill_switch_action)", menu)
        self.assertIn("self.options_menu.addAction(self.credentials_action)", menu)
        self.assertIn("self.options_menu.addAction(self.live_log_action)", menu)
        self.assertIn("self.options_menu.addAction(self.options_dialog_action)", menu)
        self.assertNotIn("self.language_menu = self.options_menu.addMenu", menu)
        self.assertNotIn("self.appearance_menu = self.options_menu.addMenu", menu)
        self.assertNotIn("self.quit_behavior_menu = self.options_menu.addMenu", menu)
        self.assertNotIn("self.options_menu.addAction(self.tray_action)", menu)
        self.assertIn('self.options_menu.setTitle(tr("menu.tools"))', self.gui)

    def test_options_dialog_contains_only_ordinary_persistent_preferences(self) -> None:
        self.assertIn('settings.value("ui/theme", "system")', self.options)
        self.assertIn('settings.value("ui/quit_behavior", "ask")', self.options)
        self.assertIn('bool_value(settings, "ui/tray_enabled", True)', self.options)
        self.assertIn("language()", self.options)
        self.assertNotIn("kill_switch", self.options.lower())
        self.assertNotIn("Credential", self.options)
        self.assertNotIn("live_log", self.options)

    def test_dialog_is_fixed_size_and_save_cancel_is_transaction_boundary(self) -> None:
        self.assertIn("self.setFixedSize(OPTIONS_DIALOG_WIDTH, OPTIONS_DIALOG_HEIGHT)", self.options)
        self.assertIn("QDialogButtonBox.StandardButton.Save", self.options)
        self.assertIn("QDialogButtonBox.StandardButton.Cancel", self.options)
        self.assertNotIn("settings.setValue", self.options)
        show = self.gui[
            self.gui.index("    def show_options") :
            self.gui.index("    def change_language", self.gui.index("    def show_options"))
        ]
        self.assertIn("if dialog.exec() != QDialog.DialogCode.Accepted:", show)
        self.assertIn("self.change_language(values.language_code)", show)
        self.assertIn("self.change_theme(values.theme)", show)
        self.assertIn("self.change_quit_behavior(values.quit_behavior)", show)
        self.assertIn("self._tray_setting_changed(values.tray_enabled)", show)

    def test_live_log_remains_a_quick_toggle_with_shortcut(self) -> None:
        self.assertIn('self.live_log_action.setShortcut(QKeySequence("Ctrl+L"))', self.gui)
        self.assertIn("self.options_menu.addAction(self.live_log_action)", self.gui)
        self.assertNotIn("ui/live_log", self.options)

    def test_credentials_remain_a_quick_command_not_an_option(self) -> None:
        self.assertIn("lambda: self.edit_credentials(first_run=False)", self.gui)
        self.assertIn("self.options_menu.addAction(self.credentials_action)", self.gui)
        self.assertNotIn("CredentialStore", self.options)

    def test_session_kill_switch_is_named_explicitly_and_stays_outside_options(self) -> None:
        self.assertEqual(self.de["menu.kill_switch"], "Session Kill Switch verwenden")
        self.assertEqual(self.en["menu.kill_switch"], "Use Session Kill Switch")
        self.assertIn("nicht bootpersistent", self.de["menu.kill_switch_tooltip"])
        self.assertIn("not persistent across reboot", self.en["menu.kill_switch_tooltip"])
        self.assertIn("self.options_menu.addAction(self.kill_switch_action)", self.gui)

    def test_options_copy_and_menu_names_are_bilingual(self) -> None:
        self.assertEqual(self.de["menu.tools"], "&Funktionen")
        self.assertEqual(self.en["menu.tools"], "&Tools")
        self.assertEqual(self.de["menu.options_dialog"], "&Optionen …")
        self.assertEqual(self.en["menu.options_dialog"], "&Options…")
        for key in (
            "options.title",
            "options.general",
            "options.language",
            "options.quit_behavior",
            "options.tray_enabled",
            "options.appearance",
            "options.theme",
        ):
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)

    def test_option_selectors_share_one_visual_grid(self) -> None:
        self.assertIn("OPTIONS_LABEL_COLUMN_WIDTH = 230", self.options)
        self.assertIn("OPTIONS_FIELD_WIDTH = 250", self.options)
        self.assertEqual(
            self.options.count("self._configure_combo("),
            3,
        )
        self.assertIn("combo.setFixedWidth(OPTIONS_FIELD_WIDTH)", self.options)
        self.assertIn("label.setFixedWidth(OPTIONS_LABEL_COLUMN_WIDTH)", self.options)
        self.assertIn(
            'self._form_label(tr("options.theme"))',
            self.options,
        )

    def test_translation_key_sets_still_match(self) -> None:
        self.assertEqual(set(self.en), set(self.de))


if __name__ == "__main__":
    unittest.main()
