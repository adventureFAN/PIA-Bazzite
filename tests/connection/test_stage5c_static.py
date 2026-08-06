from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
PROBES = ROOT / "pia_bazzite" / "network_probes.py"
SESSION_ENTRY = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "session_entry.py"
SELF_TEST = ROOT / "tools" / "kill-switch-connection-stage5c-self-test.sh"


class Stage5CStaticTests(unittest.TestCase):
    def test_gui_exposes_one_persistent_optional_kill_switch_action(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.kill_switch_action.setCheckable(True)", source)
        self.assertIn("self.kill_switch_runtime.set_feature_enabled(True)", source)
        self.assertIn("self.kill_switch_runtime.set_feature_enabled(False)", source)
        self.assertIn('self.options_menu.addAction(self.kill_switch_action)', source)

    def test_protected_gui_connect_prepares_probe_route_and_plan_before_vpn(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def connect_region(")
        end = source.index("    def disconnect(", start)
        method = source[start:end]
        protected_start = method.index("NetworkProbeBaseline.capture()")
        protected_create = method.index("create_wireguard_config(", protected_start)
        self.assertLess(protected_start, protected_create)
        self.assertLess(protected_create, method.index("read_wireguard_endpoint(config_path)"))
        self.assertLess(method.index("read_wireguard_endpoint(config_path)"), method.index("discover_physical_interface(endpoint)"))
        self.assertLess(method.index("ConnectionPlan.create("), method.index("orchestrator.connect("))
        self.assertNotIn("session.disable()", method)

    def test_protected_disconnect_requires_same_session_baseline_before_unlock(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def disconnect(")
        end = source.index("    def update_connection_status(", start)
        method = source[start:end]
        self.assertIn("if kill_switch_enabled and baseline is None:", method)
        self.assertIn("blocked_path_probe=baseline.ordinary_path_is_blocked", method)
        self.assertIn("orchestrator.disconnect_intentionally(", method)
        self.assertNotIn("session.disable()", method)

    def test_stage6c_replaces_the_old_switch_refusal_but_protected_leave_stays_refused(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self._switch_protected_region(", source)
        self.assertIn("self._confirm_server_switch(region)", source)
        self.assertNotIn("Protected server switching is intentionally deferred to Stage 6.", source)
        self.assertIn("if self.kill_switch_runtime.feature_enabled:", source)
        self.assertIn('tr("kill_switch.quit_connected_message")', source)

    def test_runtime_status_uses_only_last_verified_helper_result(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self._read_cached_kill_switch_status", source)
        self.assertIn("No verified kill-switch helper status is available", source)
        update_start = source.index("    def update_connection_status(")
        update_end = source.index("    def _update_controls(", update_start)
        self.assertNotIn("session.status()", source[update_start:update_end])

    def test_probe_module_uses_fixed_numeric_targets_and_no_shell(self) -> None:
        source = PROBES.read_text(encoding="utf-8")
        self.assertIn('IPV4_TEST_ADDRESS = "1.1.1.1"', source)
        self.assertIn('IPV6_TEST_ADDRESS = "2606:4700:4700::1111"', source)
        self.assertIn("socket.SOCK_DGRAM", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)

    def test_restricted_session_survives_a_normal_long_gui_connection(self) -> None:
        source = SESSION_ENTRY.read_text(encoding="utf-8")
        self.assertIn("IDLE_TIMEOUT_SECONDS = 12 * 60 * 60.0", source)
        self.assertIn("MAX_REQUESTS = 128", source)


    def test_blocking_or_uncertain_firewall_hides_stale_public_network_details(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("def _disconnected_kill_switch_may_block(", source)
        self.assertIn("def _show_suppressed_public_info(", source)
        self.assertIn('self.ip_value.setText("—")', source)
        self.assertIn('self.dns_value.setText("—")', source)
        refresh_start = source.index("    def refresh_public_info(")
        refresh_end = source.index("    # ------------------------------------------------------------------\n    # Tray", refresh_start)
        refresh = source[refresh_start:refresh_end]
        self.assertIn("if self._disconnected_kill_switch_may_block():", refresh)
        self.assertIn("self.ip_refresh_button.setEnabled(False)", refresh)

    def test_stage6c_uses_the_stage5c_baseline_for_fail_closed_reconnect(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def connect_region(")
        end = source.index("    def disconnect(", start)
        method = source[start:end]
        guard = method.index("self._disconnected_kill_switch_may_block(")
        capture = method.index("NetworkProbeBaseline.capture()")
        self.assertLess(guard, capture)
        self.assertIn("self._start_protected_reconnect(automatic=False)", method)
        self.assertIn("self._kill_switch_route_plan", source)

    def test_self_test_is_explicitly_unprivileged_and_network_free(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn("does not use sudo, pkexec, networking, NetworkManager, or nftables", source)
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("main.py", source)


if __name__ == "__main__":
    unittest.main()
