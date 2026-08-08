from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
EMERGENCY = ROOT / "pia_bazzite" / "emergency_reset.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage8C3BCrashRecoveryPolishTests(unittest.TestCase):
    def test_initial_server_refresh_waits_for_full_kill_switch_reconciliation(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        first_start = source[source.index("    def _first_start"):source.index("    def edit_credentials")]
        gate = source[source.index("    def _request_initial_region_refresh"):source.index("    def _first_start")]
        recovery = source[source.index("    def _reconcile_kill_switch_startup"):source.index("    def _recheck_kill_switch_status")]
        self.assertIn("self._request_initial_region_refresh()", first_start)
        self.assertNotIn("QTimer.singleShot(0, self.refresh_regions)", first_start)
        self.assertIn("self._startup_kill_switch_reconciliation_required()", gate)
        self.assertIn("self._initial_region_refresh_pending = True", gate)
        self.assertIn("self._release_initial_region_refresh_if_safe()", recovery)


    def test_successfully_adopted_blocking_startup_does_not_show_recovery_error(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        recovery = source[source.index("    def _reconcile_kill_switch_startup"):source.index("    def _recheck_kill_switch_status")]
        expected_gate = """elif (\n                not decision.adopted\n                and decision.disposition not in {"""
        self.assertIn(expected_gate, recovery)
        error_gate = recovery[recovery.index(expected_gate):recovery.index("        def failure", recovery.index(expected_gate))]
        self.assertIn("self._show_startup_recovery_failure(", error_gate)
        self.assertNotIn("self._show_error(", error_gate)


    def test_remembered_idle_kill_switch_preference_does_not_require_startup_polkit(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        gate_start = source.index("    def _startup_kill_switch_reconciliation_required(")
        gate_end = source.index("    def _reconcile_kill_switch_startup(", gate_start)
        gate = source[gate_start:gate_end]
        self.assertIn("self._kill_switch_reconciliation_marker_required()", gate)
        self.assertIn("record_path.exists() or record_path.is_symlink()", gate)
        self.assertNotIn("self.kill_switch_runtime.feature_enabled", gate)

        disconnected_start = source.index("    def _disconnected_kill_switch_may_block(")
        disconnected_end = source.index("    def _networkmanager_unknown_view_state", disconnected_start)
        disconnected = source[disconnected_start:disconnected_end]
        self.assertIn("return self._startup_kill_switch_reconciliation_required()", disconnected)
        self.assertNotIn("self._kill_switch_status is None\n            or", disconnected)

        update_start = source.index("    def update_connection_status(")
        update_end = source.index("    def _update_controls", update_start)
        update = source[update_start:update_end]
        self.assertIn("not self._startup_kill_switch_reconciliation_required()", update)
        self.assertIn("KillSwitchObservation.create(", update)
        self.assertIn("feature_enabled=True", update)
        self.assertIn("vpn_connected=False", update)

    def test_pre_firewall_marker_preserves_narrow_crash_window_detection(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        connect_start = source.index("    def connect_region(")
        connect_end = source.index("    def _schedule_protected_reconnect", connect_start)
        connect = source[connect_start:connect_end]
        marker = connect.index("self._set_kill_switch_reconciliation_marker(True)")
        worker = connect.index("        def job()")
        orchestrator = connect.index("KillSwitchConnectionOrchestrator(")
        self.assertLess(marker, worker)
        self.assertLess(marker, orchestrator)

        recovery_start = source.index("    def _reconcile_kill_switch_startup(")
        recovery_end = source.index("    def _recheck_kill_switch_status", recovery_start)
        recovery = source[recovery_start:recovery_end]
        self.assertIn("self._set_kill_switch_reconciliation_marker(False)", recovery)
        self.assertIn("self._set_kill_switch_reconciliation_marker(True)", recovery)

        safe_release_start = source.index("    def _clear_crash_recovery_record_after_safe_release")
        safe_release_end = source.index("    def _protected_reconnect_context_available", safe_release_start)
        safe_release = source[safe_release_start:safe_release_end]
        self.assertIn("self._set_kill_switch_reconciliation_marker(False)", safe_release)

    def test_integrated_emergency_reset_uses_vpn_first_verified_backend(self) -> None:
        gui = GUI.read_text(encoding="utf-8")
        backend = EMERGENCY.read_text(encoding="utf-8")
        method = gui[gui.index("    def emergency_reset(self)"):gui.index("    def _startup_ipv6_guard_reconciliation_required", gui.index("    def emergency_reset(self)"))]
        self.assertIn("run_verified_emergency_reset(", method)
        self.assertIn("KillSwitchClient(timeout=120.0)", method)
        self.assertNotIn(".disable(", method)
        vpn_disconnect = backend.index("vpn_backend.disconnect")
        vpn_verify = backend.index("verified = vpn_backend.connection_state()")
        firewall = backend.index("client.emergency_reset()")
        cleanup = backend.index("recovery_store.discard_untrusted_after_verified_release()")
        self.assertLess(vpn_disconnect, vpn_verify)
        self.assertLess(vpn_verify, firewall)
        self.assertLess(firewall, cleanup)

    def test_emergency_reset_and_quit_blocked_copy_is_complete_in_both_languages(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))
        for key in (
            "menu.emergency_reset",
            "emergency_reset.confirm_title",
            "emergency_reset.confirm_message",
            "emergency_reset.complete_title",
            "emergency_reset.complete_message",
            "emergency_reset.failed_title",
            "emergency_reset.failed_message",
            "error.kill_switch_quit_blocked.title",
            "log.kill_switch.emergency_reset.started",
            "log.kill_switch.emergency_reset.completed",
            "log.kill_switch.emergency_reset.failed",
        ):
            self.assertIn(key, de)
            self.assertIn(key, en)
        self.assertNotEqual(de["error.kill_switch_quit_blocked.title"], "error.kill_switch_quit_blocked.title")


if __name__ == "__main__":
    unittest.main()
