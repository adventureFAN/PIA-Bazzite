from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DRIVER = ROOT / "tools" / "pia-bazzite-stage7c-takeover-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7c1-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7c1-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7c1-self-test.sh"
DOC = ROOT / "docs" / "kill-switch" / "KILL_SWITCH_CRASH_STAGE7C1.md"


class Stage7C1StaticTests(unittest.TestCase):
    def test_background_worker_cannot_publish_takeover_commit(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        worker_start = method.index("        def job()")
        success_start = method.index("        def success(")
        worker = method[worker_start:success_start]
        self.assertIn("CrashRecoveryVerifier().evaluate(", worker)
        self.assertNotIn("self._crash_recovery_journal.clear()", worker)
        self.assertNotIn("self._crash_recovery_journal.save_connected(", worker)
        self.assertNotIn("self._crash_recovery_journal.save_blocking(", worker)

    def test_takeover_commit_is_ordered_after_live_session_retention(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        success = source[source.index("        def success(", start):end]
        open_guard = success.index("if not outcome.session.is_open:")
        retain = success.index("self._kill_switch_session = outcome.session")
        connected = success.index("self._crash_recovery_journal.save_connected(")
        blocking = success.index("self._crash_recovery_journal.save_blocking(")
        self.assertLess(open_guard, retain)
        self.assertLess(retain, connected)
        self.assertLess(retain, blocking)

    def test_record_commit_failure_remains_fail_closed_with_session_retained(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        success = source[source.index("        def success(", start):end]
        assignment = success.index("self._kill_switch_session = outcome.session")
        guarded_mutation = success.index("            try:", assignment)
        handler = success.index("            except Exception as exc:", guarded_mutation)
        self.assertLess(assignment, guarded_mutation)
        self.assertLess(guarded_mutation, handler)
        failure_block = success[handler:success.index("            if decision.disposition in {", handler)]
        self.assertIn("error=f\"{type(exc).__name__}: {exc}\"", failure_block)
        self.assertNotIn("self._close_kill_switch_session()", failure_block)

    def test_driver_requires_session_and_rotated_record_to_be_stable_together(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("stable_session_pid", source)
        self.assertIn("rotated_without_session_since", source)
        self.assertIn("time.monotonic() - rotated_without_session_since >= 10.0", source)
        self.assertIn(
            "retained the authenticated helper session before rotating the recovery record",
            source,
        )

    def test_host_test_and_reset_use_distinct_stage7c1_safety_unit(self) -> None:
        host = HOST_TEST.read_text(encoding="utf-8")
        reset = RESET.read_text(encoding="utf-8")
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c1-takeover-safety-reset"', host)
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c1-takeover-safety-reset"', reset)
        self.assertIn("pia-kill-switch-crash-stage7c1-host-test.txt", host)
        self.assertIn("FAIL-CLOSED STOP", host)

    def test_self_test_is_unprivileged_and_documented(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertTrue(DOC.is_file())
        self.assertIn("retained before record rotation", DOC.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
