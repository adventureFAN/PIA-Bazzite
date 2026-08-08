from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DRIVER = ROOT / "tools" / "pia-bazzite-stage7c-takeover-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7c-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7c-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7c-self-test.sh"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage7CStaticTests(unittest.TestCase):
    def test_startup_reconciliation_is_automatic_for_persisted_recovery_hint(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("QTimer.singleShot(75, self._reconcile_kill_switch_startup)", source)
        start = source.index("    def _startup_kill_switch_reconciliation_required(")
        end = source.index("    def _reconcile_kill_switch_startup(", start)
        gate = source[start:end]
        self.assertIn("self._kill_switch_reconciliation_marker_required()", gate)
        self.assertIn("record_path.exists() or record_path.is_symlink()", gate)
        self.assertNotIn("self.kill_switch_runtime.feature_enabled", gate)

    def test_adoption_uses_two_stable_helper_and_networkmanager_snapshots(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        first_status = method.index("first_status = session.status()")
        first_network = method.index("first_network = network_manager.connection_state()")
        second_status = method.index("second_status = session.status()")
        second_network = method.index("second_network = network_manager.connection_state()")
        evaluate = method.index("CrashRecoveryVerifier().evaluate(")
        self.assertLess(first_status, first_network)
        self.assertLess(first_network, second_status)
        self.assertLess(second_status, second_network)
        self.assertLess(second_network, evaluate)
        self.assertIn("first_status != second_status or first_network != second_network", method)

    def test_startup_never_modifies_vpn_or_firewall(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        for forbidden in (
            "network_manager.disconnect(",
            "network_manager.connect(",
            ".disable(",
            ".enable(",
            "emergency_reset",
            "set_interfaces(",
            "set_endpoints(",
        ):
            self.assertNotIn(forbidden, method)

    def test_record_is_rotated_only_for_exact_adoption_or_cleared_after_absence(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        evaluate = method.index("CrashRecoveryVerifier().evaluate(")
        clear = method.index("self._crash_recovery_journal.clear()")
        save_connected = method.index("self._crash_recovery_journal.save_connected(")
        save_blocking = method.index("self._crash_recovery_journal.save_blocking(")
        self.assertLess(evaluate, clear)
        self.assertLess(evaluate, save_connected)
        self.assertLess(evaluate, save_blocking)
        self.assertIn("CrashRecoveryDisposition.CLEAR_STALE_RECORD", method)
        self.assertIn("CrashRecoveryDisposition.ADOPT_CONNECTED", method)
        self.assertIn("CrashRecoveryDisposition.ADOPT_BLOCKING", method)

    def test_gui_retains_helper_session_before_rotating_takeover_record(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        worker_start = method.index("        def job()")
        success_start = method.index("        def success(")
        worker = method[worker_start:success_start]
        success = method[success_start:]
        self.assertNotIn("self._crash_recovery_journal.save_connected(", worker)
        self.assertNotIn("self._crash_recovery_journal.save_blocking(", worker)
        retain = success.index("self._kill_switch_session = outcome.session")
        save_connected = success.index("self._crash_recovery_journal.save_connected(")
        save_blocking = success.index("self._crash_recovery_journal.save_blocking(")
        self.assertLess(retain, save_connected)
        self.assertLess(retain, save_blocking)
        self.assertIn("if not outcome.session.is_open:", success)

    def test_refused_takeover_keeps_verified_lock_and_surfaces_error(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        self.assertIn("error=decision.reason", method)
        self.assertIn("log.kill_switch.startup_recovery.refused", method)
        self.assertNotIn("_clear_crash_recovery_record_after_safe_release", method)

    def test_real_driver_proves_clean_auto_session_sigkill_rotation_and_gui_release(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("_wait_for_clean_startup_reconciliation", source)
        self.assertIn("Do NOT click 'Schutzstatus neu prüfen'", source)
        self.assertIn("os.kill(first_app.pid, signal.SIGKILL)", source)
        self.assertIn("record.session_id != previous_record.session_id", source)
        self.assertIn("retained the authenticated helper session before rotating", source)
        self.assertIn("rotated the recovery record but did not retain", source)
        self.assertIn("CrashRecoveryDisposition.ADOPT_CONNECTED", source)
        self.assertIn("sentinel.stop_and_assert_clean()", source)
        self.assertIn("_wait_for_deliberate_gui_disconnect", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("shell=True", source)

    def test_host_wrapper_arms_reset_before_driver_and_never_cleans_on_failure(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        timer = source.index("sudo systemd-run")
        driver = source.index("pia-bazzite-stage7c-takeover-driver.py")
        self.assertLess(timer, driver)
        self.assertIn("FAIL-CLOSED STOP", source)
        self.assertIn("kill-switch-crash-stage7c-emergency-reset.sh", source)
        self.assertNotIn("stage7c-emergency-reset.sh\"\n    ;", source)

    def test_emergency_reset_stops_vpn_before_table_and_record_removal(self) -> None:
        source = RESET.read_text(encoding="utf-8")
        vpn = source.index("nmcli connection down")
        table = source.index('destroy table inet "$TABLE"')
        record = source.index("CrashRecoveryStore(crash_recovery_path())")
        self.assertLess(vpn, table)
        self.assertLess(table, record)

    def test_translations_match_and_describe_automatic_takeover(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))
        self.assertIn("automatisch", de["log.kill_switch.startup_recovery.started"])
        self.assertIn("sicher übernommen", de["log.kill_switch.startup_recovery.adopted_connected"])
        self.assertIn("adopted safely", en["log.kill_switch.startup_recovery.adopted_connected"])

    def test_self_test_is_unprivileged_and_does_not_run_real_host_test(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("kill-switch-crash-stage7c-host-test.sh\" \"$@", source)


if __name__ == "__main__":
    unittest.main()
