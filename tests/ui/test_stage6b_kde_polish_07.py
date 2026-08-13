from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage6BKdePolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.options = OPTIONS.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_network_privacy_tab_escapes_literal_qt_mnemonic_ampersand(self) -> None:
        self.assertEqual(self.de["options.tab.network_privacy"], "Netzwerk && Datenschutz")
        self.assertEqual(self.en["options.tab.network_privacy"], "Network && Privacy")

    def test_tabs_do_not_repeat_their_titles_inside_the_page(self) -> None:
        self.assertEqual(self.options.count("= QGroupBox()"), 3)
        for key in ("options.general", "options.connection", "options.network_privacy"):
            self.assertNotIn(f'QGroupBox(tr("{key}"))', self.options)

    def test_grid_layout_prevents_form_wrap_overlap_and_spans_checkboxes(self) -> None:
        self.assertIn("QGridLayout", self.options)
        self.assertNotIn("    QFormLayout,\n", self.options)
        self.assertNotIn("OPTIONS_LABEL_COLUMN_WIDTH", self.options)
        self.assertIn("layout.setColumnStretch(0, 1)", self.options)
        self.assertIn("layout.setColumnMinimumWidth(1, OPTIONS_FIELD_WIDTH)", self.options)
        for snippet in (
            "general_form.addWidget(self.tray_checkbox, 2, 0, 1, 2)",
            "general_form.addWidget(self.autostart_checkbox, 3, 0, 1, 2)",
            "general_form.addWidget(self.security_notifications_checkbox, 4, 0, 1, 2)",
            "connection_form.addWidget(self.confirm_server_switch_checkbox, 2, 0, 1, 2)",
            "network_form.addWidget(self.show_public_info_checkbox, 0, 0, 1, 2)",
        ):
            self.assertIn(snippet, self.options)

    def test_tray_header_copy_uses_colon_and_plain_two_line_fallback(self) -> None:
        keys = [k for k in self.de if k.startswith("tray.kill_switch_tooltip.")]
        keys += [k for k in self.de if k.startswith("tray.network_tooltip.")]
        self.assertTrue(keys)
        for key in keys:
            for catalog in (self.de, self.en):
                lines = catalog[key].splitlines()
                self.assertGreaterEqual(len(lines), 2)
                self.assertTrue(lines[0].startswith("PIA Bazzite: "))
                self.assertNotIn("—", lines[0])
                self.assertNotIn("<", catalog[key])


if __name__ == "__main__":
    unittest.main()
