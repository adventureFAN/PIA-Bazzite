from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"
SELF_TEST = ROOT / "tools" / "kill-switch-recovery-stage6c-self-test.sh"


class Stage6CStaticTests(unittest.TestCase):
    def test_gui_imports_only_the_tested_recovery_boundary(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("KillSwitchRecoveryOrchestrator", source)
        self.assertIn("FirewallRoutePlan", source)
        self.assertIn("PreparedServerSwitch", source)
        self.assertNotIn("session.disable()", source)
        self.assertNotIn("emergency_reset(", source)

    def test_initial_protected_connection_retains_exact_route_for_recovery(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def connect_region(")
        end = source.index("    def _schedule_protected_reconnect", start)
        method = source[start:end]
        self.assertLess(
            method.index("route_plan = FirewallRoutePlan.from_connection_plan(plan)"),
            method.index("orchestrator.connect("),
        )
        self.assertIn("self._kill_switch_route_plan = result.route_plan", method)

    def test_unexpected_tunnel_loss_schedules_one_protected_reconnect(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def update_connection_status(")
        end = source.index("    def _update_controls(", start)
        method = source[start:end]
        self.assertIn("previous is True", method)
        self.assertIn("not self._connection_busy", method)
        self.assertIn("self._schedule_protected_reconnect()", method)
        schedule_start = source.index("    def _schedule_protected_reconnect(")
        schedule_end = source.index("    def _start_protected_reconnect(", schedule_start)
        schedule = source[schedule_start:schedule_end]
        self.assertIn("self._protected_reconnect_scheduled", schedule)
        self.assertIn("QTimer.singleShot(", schedule)

    def test_reconnect_uses_profile_baseline_route_and_never_unlocks(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _start_protected_reconnect(")
        end = source.index("    def _switch_protected_region(", start)
        method = source[start:end]
        self.assertIn('self.settings.value("connection/profile_uuid", "")', method)
        self.assertIn("route_plan=route_plan", method)
        self.assertIn("blocked_path_probe=baseline.ordinary_path_is_blocked", method)
        self.assertNotIn("disable(", method)

    def test_orange_state_offers_reconnect_in_window_and_tray(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn('"connection.reconnect"', source)
        self.assertIn("self._protected_reconnect_context_available()", source)
        self.assertIn("self._start_protected_reconnect(automatic=False)", source)
        self.assertIn('"connection.recheck_protection"', source)

    def test_server_selection_uses_confirmation_without_new_permanent_button(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        selection_start = source.index("    def _selection_changed(")
        selection_end = source.index("    def _selected_region(", selection_start)
        selection = source[selection_start:selection_end]
        self.assertIn("self.connect_region(selected)", selection)
        self.assertIn("QMessageBox.question(", source)
        self.assertIn('"server_switch.confirm_message"', source)
        self.assertNotIn("server_switch_button", source)

    def test_protected_switch_prepares_candidate_then_uses_offline_orchestrator(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _switch_protected_region(")
        end = source.index("    def disconnect(", start)
        method = source[start:end]
        candidate = method.index("PreparedServerSwitch.create(config_path=config_path)")
        orchestrator = method.index("orchestrator.switch_server(", candidate)
        self.assertLess(candidate, orchestrator)
        self.assertIn("blocked_path_probe=baseline.ordinary_path_is_blocked", method)
        self.assertIn("physical_interface_resolver=resolve_existing_physical_interface", method)
        self.assertNotIn("disable(", method)

    def test_untested_physical_interface_change_is_refused_fail_closed(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("if interface not in current_route.physical_interfaces:", source)
        self.assertIn("dedicated ", source)
        self.assertIn("Wi-Fi/LAN recovery stage", source)

    def test_failed_switch_after_old_vpn_down_drops_unsafe_reconnect_route(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _switch_protected_region(")
        end = source.index("    def disconnect(", start)
        method = source[start:end]
        self.assertIn("and exc.old_vpn_disconnected", method)
        self.assertIn("retained_route = None", method)
        self.assertIn("self._kill_switch_route_plan = error.route_plan", method)

    def test_internal_connection_results_update_cached_state_before_status_refresh(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("self._last_connected_state = True"), 3)
        self.assertIn("self._last_connected_state = False", source)
        self.assertIn('"log.external_connected" if connected else "log.external_disconnected"', source)

    def test_recovery_translations_are_complete_and_equal(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))
        required = {
            "connection.reconnect",
            "server_switch.confirm_title",
            "server_switch.confirm_message",
            "error.kill_switch_recovery.title",
            "error.kill_switch_recovery.message",
            "error.kill_switch_switch_failed.title",
            "error.kill_switch_switch_failed.message",
            "log.kill_switch.recovery.tunnel_lost",
            "log.kill_switch.recovery.reconnect_complete",
            "log.kill_switch.recovery.switch_complete",
        }
        self.assertTrue(required.issubset(de))

    def test_self_test_is_unprivileged_and_does_not_start_the_gui(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, or the leak sentinel",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("./run.sh", source)
        self.assertNotIn("stage6b-host-test.sh\" \"$@", source)


if __name__ == "__main__":
    unittest.main()
