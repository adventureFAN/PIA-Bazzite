from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite/gui.py"
I18N = ROOT / "pia_bazzite/i18n.py"
SPEC = ROOT / "packaging/appimage/PIA-Bazzite.spec"
RESOURCE_DIR = ROOT / "pia_bazzite/resources/i18n"


class Stage8C3AFinalPolishTests(unittest.TestCase):
    def test_qt_standard_dialog_german_translation_is_runtime_managed_and_packaged(self) -> None:
        i18n = I18N.read_text(encoding="utf-8")
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("QTranslator", i18n)
        self.assertIn("qtbase_de.qm", i18n)
        self.assertIn("app.removeTranslator", i18n)
        self.assertIn("app.installTranslator", i18n)
        self.assertIn("qtbase_de.qm", spec)
        self.assertIn("PySide6/Qt/translations", spec)
        gui = GUI.read_text(encoding="utf-8")
        self.assertIn('tr("log.file_filter")', gui)

    def test_region_popup_is_limited_to_twenty_visible_items(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("REGION_POPUP_VISIBLE_ITEMS = 20", source)
        self.assertIn("setMaxVisibleItems(REGION_POPUP_VISIBLE_ITEMS)", source)
        self.assertIn("][:20]", source.replace(" ", ""))

    def test_live_log_tail_follows_only_when_appropriate_and_on_return(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("def _scroll_live_log_to_end", source)
        self.assertIn("scrollbar.maximum() - 2", source)
        self.assertIn("not self.log_view.isVisible()", source)
        self.assertGreaterEqual(source.count("QTimer.singleShot(0, self._scroll_live_log_to_end)"), 3)

    def test_public_ip_reload_button_is_smaller(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.ip_refresh_button.setFixedSize(24, 22)", source)
        self.assertNotIn("self.ip_refresh_button.setFixedSize(28, 24)", source)

    def test_custom_about_dialog_matches_shared_app_structure(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("class AboutDialog(QDialog)", source)
        self.assertIn('status_icon("application", 104)', source)
        self.assertIn('QPushButton(tr("about.project_page"))', source)
        self.assertNotIn('QPushButton(tr("about.open_log_folder"))', source)
        self.assertIn('QPushButton(tr("about.third_party_notices"))', source)
        self.assertIn("developer_label.setWordWrap(True)", source)
        self.assertIn("ThirdPartyNoticesDialog(self).exec()", source)
        self.assertIn("AboutDialog(self).exec()", source)
        self.assertNotIn("QMessageBox.about(", source)

    def test_kill_switch_helper_dialog_explains_two_first_setup_prompts(self) -> None:
        de = json.loads((RESOURCE_DIR / "de.json").read_text(encoding="utf-8"))
        en = json.loads((RESOURCE_DIR / "en.json").read_text(encoding="utf-8"))
        for language_data in (de, en):
            self.assertGreaterEqual(
                language_data["kill_switch.helper_install.install_message"].count("\n\n"),
                2,
            )
            self.assertGreaterEqual(
                language_data["kill_switch.helper_install.update_message"].count("\n\n"),
                2,
            )
        self.assertIn("zwei Administratorabfragen", de["kill_switch.helper_install.install_message"])
        self.assertIn("two administrator prompts", en["kill_switch.helper_install.install_message"])

    def test_automatic_public_info_refresh_does_not_repeat_identical_log_entry(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        refresh_start = source.index("    def refresh_public_info(")
        refresh_end = source.index(
            "    # ------------------------------------------------------------------\n    # Tray",
            refresh_start,
        )
        refresh = source[refresh_start:refresh_end]
        self.assertIn("previous_public_info = self.public_info", refresh)
        self.assertIn("if show_errors or previous_public_info != result:", refresh)
        self.assertIn('"log.public_info"', refresh)

    def test_about_translations_are_complete_in_both_languages(self) -> None:
        de = json.loads((RESOURCE_DIR / "de.json").read_text(encoding="utf-8"))
        en = json.loads((RESOURCE_DIR / "en.json").read_text(encoding="utf-8"))
        keys = {
            "about.version", "about.description", "about.license",
            "about.developer", "about.disclaimer", "about.project_page",
            "about.third_party_notices",
            "about.third_party_title", "about.third_party_unavailable",
        }
        self.assertTrue(keys <= set(de))
        self.assertTrue(keys <= set(en))
        self.assertIn("adventureFAN", en["about.developer"])
        self.assertIn("ChatGPT", en["about.developer"])
        self.assertIn("adventureFAN", de["about.developer"])
        self.assertIn("ChatGPT", de["about.developer"])


if __name__ == "__main__":
    unittest.main()
