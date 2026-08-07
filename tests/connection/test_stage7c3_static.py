from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
SESSION = ROOT / "pia_bazzite" / "kill_switch_session.py"
DRIVER = ROOT / "tools" / "pia-bazzite-stage7c3-takeover-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7c3-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7c3-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7c3-self-test.sh"
DOC = ROOT / "docs" / "kill-switch" / "KILL_SWITCH_CRASH_STAGE7C3.md"


class Stage7C3StaticTests(unittest.TestCase):
    def test_real_transport_liveness_drives_client_is_open(self) -> None:
        source = SESSION.read_text(encoding="utf-8")
        self.assertIn("def is_alive(self) -> bool:", source)
        self.assertIn("return process is not None and process.poll() is None", source)
        self.assertIn('checker = getattr(self.transport, "is_alive", None)', source)

    def test_gui_probes_exact_session_after_worker_handoff_before_rotation(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("def _reconcile_kill_switch_startup")
        end = source.index("def _recheck_kill_switch_status", start)
        method = source[start:end]
        assignment = method.index("self._kill_switch_session = outcome.session")
        handoff_probe = method.index("retained_status = outcome.session.status()")
        rotation = method.index("self._crash_recovery_journal.save_connected", handoff_probe)
        self.assertLess(assignment, handoff_probe)
        self.assertLess(handoff_probe, rotation)
        self.assertIn("retained-session handoff", method)

    def test_driver_proves_all_three_private_transport_pipes(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("class SessionPipeBinding", source)
        self.assertIn("def _privileged_session_pipe_probe", source)
        self.assertIn('stdio = [helper_pipes.get(str(fd), "") for fd in (0, 1, 2)]', source)
        self.assertIn("all(value in app_pipe_values for value in stdio)", source)
        self.assertIn("reparented but still pipe-bound", source)
        self.assertNotIn("_session_descendant(app_process.pid", source)

    def test_host_test_and_reset_have_distinct_stage7c3_names(self) -> None:
        host = HOST_TEST.read_text(encoding="utf-8")
        reset = RESET.read_text(encoding="utf-8")
        self_test = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c3-takeover-safety-reset"', host)
        self.assertIn("pia-bazzite-stage7c3-takeover-driver.py", host)
        self.assertIn("PIPE-BOUND RETAINED-SESSION PROOF HOST TESTS PASSED", host)
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c3-takeover-safety-reset"', reset)
        self.assertNotIn("sudo ", self_test)

    def test_stage7c3_is_documented(self) -> None:
        self.assertTrue(DOC.is_file())
        documentation = DOC.read_text(encoding="utf-8").lower()
        self.assertIn("three private stdio pipes", documentation)
        self.assertIn("reparent", documentation)
        self.assertIn("post-handoff status", documentation)


if __name__ == "__main__":
    unittest.main()
