from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tools" / "pia-bazzite-stage7c-takeover-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7c2-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7c2-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7c2-self-test.sh"
DOC = ROOT / "docs" / "kill-switch" / "KILL_SWITCH_CRASH_STAGE7C2.md"


class Stage7C2StaticTests(unittest.TestCase):
    def test_driver_distinguishes_unreadable_root_cmdline_from_missing_session(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("def _unprivileged_session_descendant", source)
        self.assertIn("def _privileged_session_descendant", source)
        self.assertIn("_PRIVILEGED_SESSION_PROBE", source)
        self.assertIn('str(SUDO_PATH),\n            "-n",', source)
        self.assertIn("return _privileged_session_descendant(app_pid)", source)

    def test_takeover_uses_privileged_descendant_proof(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("def _wait_for_connected_takeover(")
        end = source.index("def _wait_for_deliberate_gui_disconnect(", start)
        method = source[start:end]
        self.assertIn(
            "_session_descendant(app_process.pid, privileged=True)",
            method,
        )
        self.assertIn("Root-visible restricted helper PID", method)
        self.assertIn("stable_session_pid", method)

    def test_clean_start_probe_remains_unprivileged(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("def _wait_for_clean_startup_reconciliation(")
        end = source.index("def _same_recovery_payload(", start)
        method = source[start:end]
        self.assertIn(
            "_session_descendant(app_process.pid, privileged=False)",
            method,
        )

    def test_host_test_keeps_sudo_ticket_alive_for_root_proc_proof(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c2-takeover-safety-reset"', source)
        self.assertIn("sudo -n -v", source)
        self.assertIn("SUDO_KEEPALIVE_PID", source)
        self.assertIn("pia-kill-switch-crash-stage7c2-host-test.txt", source)
        self.assertIn("FAIL-CLOSED STOP", source)

    def test_reset_and_self_test_are_distinct_and_documented(self) -> None:
        reset = RESET.read_text(encoding="utf-8")
        self_test = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c2-takeover-safety-reset"', reset)
        self.assertNotIn("sudo ", self_test)
        self.assertTrue(DOC.is_file())
        documentation = DOC.read_text(encoding="utf-8").lower()
        self.assertIn("unprivileged `/proc", documentation)
        self.assertIn("root-visible", documentation)


if __name__ == "__main__":
    unittest.main()
