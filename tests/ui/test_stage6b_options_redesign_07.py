from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage6BOptionsRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.options = OPTIONS.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_options_use_three_fixed_size_tabs(self) -> None:
        self.assertIn("QTabWidget", self.options)
        self.assertIn("OPTIONS_DIALOG_WIDTH = 560", self.options)
        self.assertIn("OPTIONS_DIALOG_HEIGHT = 420", self.options)
        self.assertIn(
            "self.setFixedSize(OPTIONS_DIALOG_WIDTH, OPTIONS_DIALOG_HEIGHT)",
            self.options,
        )
        self.assertIn('tabs.addTab(general_page, tr("options.tab.general"))', self.options)
        self.assertIn(
            'tabs.addTab(connection_page, tr("options.tab.connection"))',
            self.options,
        )
        self.assertIn(
            'tabs.addTab(network_page, tr("options.tab.network_privacy"))',
            self.options,
        )

    def test_tab_labels_escape_literal_ampersand_and_redundant_inner_titles_are_removed(self) -> None:
        self.assertEqual(self.de["options.tab.network_privacy"], "Netzwerk && Datenschutz")
        self.assertEqual(self.en["options.tab.network_privacy"], "Network && Privacy")
        self.assertIn("&&", self.de["options.tab.network_privacy"])
        self.assertIn("&&", self.en["options.tab.network_privacy"])
        self.assertIn("general_group = QGroupBox()", self.options)
        self.assertIn("connection_group = QGroupBox()", self.options)
        self.assertIn("network_group = QGroupBox()", self.options)
        self.assertNotIn('QGroupBox(tr("options.general"))', self.options)
        self.assertNotIn('QGroupBox(tr("options.connection"))', self.options)
        self.assertNotIn('QGroupBox(tr("options.network_privacy"))', self.options)

    def test_standalone_checkboxes_span_the_grid_and_selectors_share_right_column(self) -> None:
        for row in (
            "general_form.addWidget(self.tray_checkbox, 2, 0, 1, 2)",
            "general_form.addWidget(self.autostart_checkbox, 3, 0, 1, 2)",
            "general_form.addWidget(self.security_notifications_checkbox, 4, 0, 1, 2)",
            "connection_form.addWidget(self.confirm_server_switch_checkbox, 2, 0, 1, 2)",
            "network_form.addWidget(self.show_public_info_checkbox, 0, 0, 1, 2)",
        ):
            self.assertIn(row, self.options)
        self.assertIn("QGridLayout", self.options)
        self.assertNotIn("    QFormLayout,\n", self.options)
        self.assertNotIn("OPTIONS_LABEL_COLUMN_WIDTH", self.options)
        self.assertIn("layout.setColumnStretch(0, 1)", self.options)
        self.assertIn("layout.setColumnMinimumWidth(1, OPTIONS_FIELD_WIDTH)", self.options)

    def test_tray_tooltips_use_colon_header_without_risky_rich_text_hacks(self) -> None:
        keys = (
            "tray.kill_switch_tooltip.active",
            "tray.kill_switch_tooltip.armed",
            "tray.kill_switch_tooltip.blocking",
            "tray.kill_switch_tooltip.error",
            "tray.kill_switch_tooltip.ready",
            "tray.kill_switch_tooltip.vpn_only",
            "tray.network_tooltip.protected",
            "tray.network_tooltip.unprotected",
        )
        for key in keys:
            for catalog in (self.de, self.en):
                first, *rest = catalog[key].splitlines()
                self.assertTrue(first.startswith("PIA Bazzite: "))
                self.assertNotIn("—", first)
                self.assertTrue(rest)
                self.assertNotIn("<", catalog[key])

    def test_new_preferences_default_to_safe_existing_behavior(self) -> None:
        self.assertIn(
            'bool_value(settings, "ui/security_notifications", True)',
            self.options,
        )
        self.assertIn(
            'bool_value(settings, "connection/confirm_server_switch", True)',
            self.options,
        )
        self.assertIn(
            'bool_value(settings, "ui/show_public_info", True)',
            self.options,
        )
        self.assertIn(
            "security_notifications=self.security_notifications_checkbox.isChecked()",
            self.options,
        )
        self.assertIn(
            "confirm_server_switch=self.confirm_server_switch_checkbox.isChecked()",
            self.options,
        )
        self.assertIn(
            "show_public_info=self.show_public_info_checkbox.isChecked()",
            self.options,
        )

    def test_server_switch_confirmation_can_be_disabled_without_changing_switch_path(self) -> None:
        start = self.gui.index("    def _confirm_server_switch")
        end = self.gui.index("    def _selected_region", start)
        block = self.gui[start:end]
        self.assertIn('"connection/confirm_server_switch", True', block)
        self.assertIn("return True", block)
        self.assertIn("QMessageBox.question", block)
        self.assertIn("if not self._confirm_server_switch(region):", self.gui)

    def test_public_info_toggle_hides_rows_and_disables_external_lookup(self) -> None:
        self.assertIn("self.ip_widget = QWidget()", self.gui)
        self.assertIn("def _apply_public_info_visibility", self.gui)
        self.assertIn("self.ip_caption", self.gui)
        self.assertIn("self.country_caption", self.gui)
        self.assertIn('bool_value(self.settings, "ui/show_public_info", True)', self.gui)

        start = self.gui.index("    def refresh_public_info")
        end = self.gui.index("    def _rebuild_tray_menu", start)
        refresh = self.gui[start:end]
        early = refresh.index("if not self._public_info_visible():")
        fetch = refresh.index("fetch_public_network_info")
        self.assertLess(early, fetch)
        self.assertIn("self.public_info = None", refresh[:fetch])

        self.assertIn(
            "self.show_public_info_checkbox.toggled.connect(\n"
            "            self.public_network_provider_combo.setEnabled",
            self.options,
        )

    def test_security_notifications_are_complementary_not_duplicate_connection_popups(self) -> None:
        self.assertIn("def _show_security_notification", self.gui)
        self.assertIn('"ui/security_notifications", True', self.gui)
        self.assertIn('"notification.kill_switch_blocking.title"', self.gui)
        self.assertIn('"notification.kill_switch_error.title"', self.gui)
        self.assertIn('"notification.auto_connect_failed.title"', self.gui)
        self.assertIn("if self.isVisible():", self.gui)
        self.assertIn("QSystemTrayIcon.supportsMessages()", self.gui)

        notify_start = self.gui.index("    def _show_security_notification")
        notify_end = self.gui.index("    # ------------------------------------------------------------------\n    # Logging", notify_start)
        notify = self.gui[notify_start:notify_end]
        self.assertNotIn("external_connected", notify)
        self.assertNotIn("external_disconnected", notify)

    def test_close_to_tray_no_longer_emits_redundant_hint_notification(self) -> None:
        close_start = self.gui.index("    def closeEvent")
        close_block = self.gui[close_start:]
        self.assertIn("self.hide()", close_block)
        self.assertNotIn("tray.hidden_message", close_block)
        self.assertNotIn("_close_hint_shown", self.gui)
        self.assertNotIn("tray.hidden_message", self.de)
        self.assertNotIn("tray.hidden_message", self.en)

    def test_marker_tooltips_keep_virtual_explanation_and_streaming_legend_only(self) -> None:
        self.assertEqual(
            self.de["region.virtual_tooltip"],
            "Virtueller Standort\nDer Server befindet sich physisch in einem anderen Land.",
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

    def test_bilingual_copy_and_translation_key_parity(self) -> None:
        keys = (
            "options.tab.general",
            "options.tab.connection",
            "options.tab.network_privacy",
            "options.security_notifications",
            "options.security_notifications_tooltip",
            "options.confirm_server_switch",
            "options.confirm_server_switch_tooltip",
            "options.show_public_info",
            "options.show_public_info_tooltip",
            "notification.kill_switch_blocking.title",
            "notification.kill_switch_error.title",
            "notification.auto_connect_failed.title",
        )
        for key in keys:
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertEqual(set(self.de), set(self.en))


if __name__ == "__main__":
    unittest.main()
