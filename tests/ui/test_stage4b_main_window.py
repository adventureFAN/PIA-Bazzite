from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
STATE = ROOT / "pia_bazzite" / "kill_switch_state.py"
WIDGETS = ROOT / "pia_bazzite" / "kill_switch_widgets.py"
PREVIEW = ROOT / "tools" / "pia-bazzite-stage4b-main-window-preview.py"
RESOURCE_DIR = ROOT / "pia_bazzite" / "resources" / "i18n"


class Stage4BMainWindowStaticTests(unittest.TestCase):
    def test_real_main_window_contains_compact_status_widget(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.kill_switch_status_widget = KillSwitchStatusWidget()", source)
        self.assertIn("self.kill_switch_status_widget.hide()", source)
        self.assertIn("self.kill_switch_status_widget.show()", source)
        self.assertIn("stage4_preview: bool = False", source)


    def test_preview_disables_all_real_connection_actions(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        for action in (
            "self.toggle_vpn_action",
            "self.reload_action",
            "self.ping_action",
            "self.ip_action",
            "self.system_action",
            "self.credentials_action",
        ):
            self.assertIn(action, source)
        self.assertIn("action.setEnabled(False)", source)

    def test_preview_hides_legacy_duplicate_status_copy(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.status_label.hide()", source)
        self.assertIn("self.status_detail_label.hide()", source)
        self.assertIn("self.kill_switch_caption.hide()", source)
        self.assertIn("self.kill_switch_value.hide()", source)

    def test_visible_copy_is_short_and_full_explanation_is_a_tooltip(self) -> None:
        source = WIDGETS.read_text(encoding="utf-8")
        self.assertIn("tr(self._state.summary_key)", source)
        self.assertIn("tooltip = tr(self._state.detail_key)", source)
        self.assertIn("self.setToolTip(tooltip)", source)
        self.assertNotIn("setText(tr(self._state.detail_key))", source)

    def test_state_model_has_separate_summary_and_detail_keys(self) -> None:
        source = STATE.read_text(encoding="utf-8")
        self.assertIn("summary_key: str", source)
        for mode in ("ready", "armed", "vpn_only", "active", "blocking", "error"):
            self.assertIn(f'"summary_key": "kill_switch.summary.{mode}"', source)

    def test_german_labels_minimize_security_ambiguity(self) -> None:
        german = json.loads(
            (RESOURCE_DIR / "de.json").read_text(encoding="utf-8")
        )
        expected = {
            "kill_switch.state.ready": "VPN bereit",
            "kill_switch.state.armed": "VPN & Kill Switch bereit",
            "kill_switch.state.vpn_only": "VPN verbunden",
            "kill_switch.state.active": "Geschützt",
            "kill_switch.state.blocking": "Sicher blockiert",
            "kill_switch.state.error": "Schutzfehler",
            "kill_switch.summary.ready": "VPN getrennt · Normale Verbindung aktiv",
            "kill_switch.summary.armed": "VPN getrennt · Schutz beim nächsten Verbinden",
            "kill_switch.summary.vpn_only": "Kill Switch ausgeschaltet",
            "kill_switch.summary.active": "VPN verbunden · Kill Switch verifiziert",
            "kill_switch.summary.blocking": "VPN getrennt · Kein normaler Internetzugang",
            "kill_switch.summary.error": "Schutz nicht garantiert · Details im Live-Log",
        }
        for key, value in expected.items():
            self.assertEqual(german[key], value)
        self.assertIn("echten öffentlichen IP", german["kill_switch.detail.ready"])
        self.assertIn("nächsten VPN-Verbindungsaufbau", german["kill_switch.detail.armed"])
        self.assertIn("echten öffentlichen IP", german["kill_switch.detail.vpn_only"])
        self.assertIn("außerhalb des VPN-Tunnels", german["kill_switch.detail.active"])
        self.assertIn("echte öffentliche IP", german["kill_switch.detail.blocking"])
        self.assertIn("nicht gestartet oder getrennt", german["kill_switch.detail.error"])

    def test_log_copy_is_event_focused_without_packet_counters(self) -> None:
        for language in ("de", "en"):
            translations = json.loads(
                (RESOURCE_DIR / f"{language}.json").read_text(encoding="utf-8")
            )
            messages = " ".join(
                translations[f"log.kill_switch.{mode}"]
                for mode in ("ready", "armed", "vpn_only", "active", "blocking", "error")
            ).casefold()
            for forbidden in ("packet", "paket", "byte", "counter", "zähler"):
                self.assertNotIn(forbidden, messages)

    def test_preview_uses_real_main_window_without_network_actions(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("from pia_bazzite.gui import MainWindow", source)
        self.assertIn("stage4_preview=True", source)
        self.assertIn('app.setApplicationDisplayName("PIA Bazzite")', source)
        self.assertNotIn("network_manager.", source)
        self.assertNotIn("KillSwitchSessionClient", source)
        self.assertNotIn("pkexec", source)
        self.assertNotIn("nft ", source)

    def test_preview_has_one_window_title(self) -> None:
        gui_source = GUI.read_text(encoding="utf-8")
        preview_source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn('self.setWindowTitle("")', gui_source)
        self.assertNotIn("setWindowTitle", preview_source)

    def test_preview_menu_exposes_all_states_and_shortcuts(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.preview_menu", source)
        self.assertIn('QKeySequence(f"Ctrl+{index + 1}")', source)
        self.assertIn("self._set_stage4_preview_state", source)


if __name__ == "__main__":
    unittest.main()
