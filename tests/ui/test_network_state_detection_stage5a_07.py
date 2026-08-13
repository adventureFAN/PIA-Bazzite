from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage5ANetworkStateUiStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_nmcli_monitor_is_event_trigger_only_and_has_fallback_poll(self) -> None:
        start = self.gui.index("    def _start_network_monitor")
        end = self.gui.index("    def _physical_network_overlay_state", start)
        block = self.gui[start:end]
        self.assertIn('process.setArguments(["monitor"])', block)
        self.assertIn("process.readAllStandardOutput()", block)
        self.assertNotIn("decode(", block)
        self.assertNotIn("connected (", block)
        self.assertIn("self.update_physical_network_status()", block)
        self.assertIn(
            "self.status_timer.timeout.connect(self.update_physical_network_status)",
            self.gui,
        )

    def test_underlay_state_uses_authoritative_network_manager_reader(self) -> None:
        start = self.gui.index("    def update_physical_network_status")
        end = self.gui.index("    def update_connection_status", start)
        block = self.gui[start:end]
        self.assertIn("network_manager.physical_network_available()", block)
        self.assertIn('"log.network.physical_lost"', block)
        self.assertIn('"log.network.physical_restored"', block)
        self.assertIn("self.update_connection_status(force=True)", block)

    def test_protected_loss_is_orange_without_rewriting_runtime_mode(self) -> None:
        start = self.gui.index("    def _physical_network_overlay_state")
        end = self.gui.index("    def _apply_physical_network_overlay", start)
        block = self.gui[start:end]
        self.assertIn('state.mode.value == "active"', block)
        self.assertIn("protection_guaranteed", block)
        self.assertIn("mode=state.mode", block)
        self.assertIn('icon_state="blocking"', block)
        self.assertIn('summary_key="network.summary.protected"', block)

    def test_normal_vpn_loss_is_neutral_not_false_blue(self) -> None:
        start = self.gui.index("    def _physical_network_overlay_state")
        end = self.gui.index("    def _apply_physical_network_overlay", start)
        block = self.gui[start:end]
        self.assertIn('state.mode.value == "vpn_only"', block)
        self.assertIn('icon_state="ready"', block)
        self.assertIn('summary_key="network.summary.unprotected"', block)

    def test_protection_errors_keep_priority_over_network_overlay(self) -> None:
        start = self.gui.index("    def _physical_network_overlay_state")
        end = self.gui.index("    def _apply_physical_network_overlay", start)
        block = self.gui[start:end]
        self.assertLess(block.index("if state.is_error"), block.index('state.mode.value == "active"'))

    def test_offline_underlay_disables_new_connection_and_server_switch_surfaces(self) -> None:
        controls = self.gui[
            self.gui.index("    def _update_controls") : self.gui.index(
                "    # ------------------------------------------------------------------\n    # Public network information",
                self.gui.index("    def _update_controls"),
            )
        ]
        self.assertIn("physical_network_ready = self._physical_network_available is not False", controls)
        self.assertIn("and physical_network_ready", controls)
        tray = self.gui[
            self.gui.index("    def _rebuild_tray_menu") : self.gui.index(
                "    def _add_tray_favorites_menu",
                self.gui.index("    def _rebuild_tray_menu"),
            )
        ]
        self.assertIn("physical_network_ready", tray)
        self.assertIn('tr("tray.status_network_unavailable")', tray)

    def test_monitor_is_stopped_during_real_quit(self) -> None:
        start = self.gui.index("    def _final_quit")
        end = self.gui.index("    def closeEvent", start)
        self.assertIn("self._stop_network_monitor()", self.gui[start:end])

    def test_bilingual_network_copy_is_complete(self) -> None:
        keys = (
            "network.detail.protected",
            "network.detail.unprotected",
            "network.state.unavailable",
            "network.summary.protected",
            "network.summary.unprotected",
            "log.network.monitor_fallback",
            "log.network.physical_lost",
            "log.network.physical_restored",
            "log.network.protection_retained",
            "log.network.vpn_waiting",
            "tray.status_network_unavailable",
            "tray.network_status.protected",
            "tray.network_status.unprotected",
            "tray.network_tooltip.protected",
            "tray.network_tooltip.unprotected",
        )
        for key in keys:
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertEqual(set(self.de), set(self.en))


if __name__ == "__main__":
    unittest.main()
