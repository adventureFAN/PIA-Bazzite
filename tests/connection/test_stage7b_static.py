from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
CRASH_STATE = ROOT / "pia_bazzite" / "kill_switch_crash_state.py"
SETTINGS = ROOT / "pia_bazzite" / "settings.py"
DRIVER = ROOT / "tools" / "pia-bazzite-stage7b-crash-driver.py"
PREFLIGHT = ROOT / "tools" / "pia-bazzite-stage7b-record-preflight.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7b-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7b-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7b-self-test.sh"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage7BStaticTests(unittest.TestCase):
    def test_gui_uses_one_fixed_private_crash_recovery_journal(self) -> None:
        gui = GUI.read_text(encoding="utf-8")
        settings = SETTINGS.read_text(encoding="utf-8")
        self.assertIn("CrashRecoveryJournal", gui)
        self.assertIn("CrashRecoveryStore(crash_recovery_path())", gui)
        self.assertIn('"kill-switch-crash-recovery-v1.json"', settings)

    def test_verified_connect_reconnect_and_switch_persist_before_success_returns(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        connect_start = source.index("    def connect_region(")
        reconnect_start = source.index("    def _start_protected_reconnect(")
        switch_start = source.index("    def _switch_protected_region(")
        disconnect_start = source.index("    def disconnect(")

        connect = source[connect_start:reconnect_start]
        reconnect = source[reconnect_start:switch_start]
        switch = source[switch_start:disconnect_start]

        self.assertLess(
            connect.index("self._save_connected_crash_recovery_record("),
            connect.index("return _ProtectedConnectOutcome("),
        )
        self.assertLess(
            reconnect.index("self._save_connected_crash_recovery_record("),
            reconnect.index("return _ProtectedReconnectOutcome("),
        )
        self.assertLess(
            switch.index("self._save_connected_crash_recovery_record("),
            switch.index("return _ProtectedServerSwitchOutcome("),
        )

    def test_tunnel_loss_updates_blocking_hint_without_opening_firewall(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _schedule_protected_reconnect(")
        end = source.index("    def _start_protected_reconnect(", start)
        method = source[start:end]
        self.assertIn("self._save_blocking_crash_recovery_record(", method)
        self.assertNotIn(".disable(", method)
        self.assertNotIn("emergency_reset", method)

    def test_record_is_cleared_only_after_safe_absence_or_verified_release(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        recheck_start = source.index("    def _recheck_kill_switch_status(")
        recheck_end = source.index("    def _log_connection_events(", recheck_start)
        recheck = source[recheck_start:recheck_end]
        self.assertLess(
            recheck.index("if outcome.status.present:"),
            recheck.index("self._clear_crash_recovery_record_after_safe_release()"),
        )

        disconnect_start = source.index("    def disconnect(")
        disconnect_end = source.index("    def _disconnected_kill_switch_may_block(", disconnect_start)
        disconnect = source[disconnect_start:disconnect_end]
        self.assertIn("self._clear_crash_recovery_record_after_safe_release()", disconnect)

        quit_start = source.index("    def request_quit(")
        close_start = source.index("    def closeEvent(", quit_start)
        lifecycle = source[quit_start:close_start]
        self.assertNotIn("_clear_crash_recovery_record", lifecycle)

    def test_crash_driver_kills_exact_gui_pid_and_verifies_all_independent_facts(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("os.kill(app_process.pid, signal.SIGKILL)", source)
        self.assertIn("CrashRecoveryVerifier()", source)
        self.assertIn("CrashRecoveryDisposition.ADOPT_CONNECTED", source)
        self.assertIn("sentinel.assert_running_and_clean", source)
        self.assertIn("network_manager.connection_state()", source)
        self.assertIn("_require_verified_lock", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("shell=True", source)

    def test_host_wrapper_arms_reset_before_driver_and_cleans_only_after_proof(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        timer = source.index("sudo systemd-run")
        driver = source.index("pia-bazzite-stage7b-crash-driver.py")
        cleanup = source.index("kill-switch-crash-stage7b-emergency-reset.sh")
        self.assertLess(timer, driver)
        self.assertLess(driver, cleanup)
        self.assertIn("FAIL-CLOSED STOP", source)
        self.assertTrue(PREFLIGHT.is_file())

    def test_emergency_reset_stops_vpn_before_table_and_record_removal(self) -> None:
        source = RESET.read_text(encoding="utf-8")
        vpn = source.index("nmcli connection down")
        table = source.index('destroy table inet "$TABLE"')
        record = source.index("CrashRecoveryStore(crash_recovery_path())")
        self.assertLess(vpn, table)
        self.assertLess(table, record)

    def test_stage7c_supersedes_the_stage7b_startup_deferral(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("CrashRecoveryVerifier", source)
        self.assertIn("CrashRecoveryDisposition.ADOPT_CONNECTED", source)
        self.assertIn("CrashRecoveryDisposition.ADOPT_BLOCKING", source)

    def test_translation_sets_match_and_explain_record_actions(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))
        self.assertIn("verifizierten Schutz", de["log.kill_switch.crash_record.connected_saved"])
        self.assertIn("sicher blockierten Zustand", de["log.kill_switch.crash_record.blocking_saved"])
        self.assertIn("safe release", en["log.kill_switch.crash_record.cleared"])

    def test_self_test_is_unprivileged_and_never_runs_real_crash_tools(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("kill-switch-crash-stage7b-host-test.sh\" \"$@", source)

    def test_crash_state_journal_has_no_firewall_or_network_side_effects(self) -> None:
        source = CRASH_STATE.read_text(encoding="utf-8")
        journal_start = source.index("class CrashRecoveryJournal:")
        journal_end = source.index("def _decision(", journal_start)
        journal = source[journal_start:journal_end]
        for forbidden in ("subprocess", "nmcli", "nft ", "pkexec", ".disable("):
            self.assertNotIn(forbidden, journal)


if __name__ == "__main__":
    unittest.main()
