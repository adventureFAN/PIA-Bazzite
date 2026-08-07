from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tools" / "pia-bazzite-stage7c4-takeover-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7c4-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7c4-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7c4-self-test.sh"
DOC = ROOT / "docs" / "kill-switch" / "KILL_SWITCH_CRASH_STAGE7C4.md"


class Stage7C4StaticTests(unittest.TestCase):
    def test_probe_excludes_its_own_process_family(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("probe_family = ancestor_chain(probe_pid)", source)
        self.assertIn("if pid in probe_family:", source)
        self.assertIn("if not shared:", source)
        self.assertNotIn("if needle not in cmdline", source)

    def test_root_pipe_peer_does_not_require_helper_path_in_cmdline(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("if (\n            isinstance(pid, int)")
        end = source.index("bindings.append(", start)
        acceptance = source[start:end]
        self.assertIn("uid == 0", acceptance)
        self.assertIn("pipe_bound is True", acceptance)
        self.assertIn("isinstance(expected_path, bool)", acceptance)
        self.assertNotIn("expected_path is True", acceptance)
        self.assertNotIn("SESSION_HELPER in cmdline", acceptance)

    def test_failure_summary_exposes_every_shared_pipe_holder(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn('f"pid={pid},ppid={ppid},uid={uid}', source)
        self.assertIn('f"shared={shared},exe={executable!r},cmdline={cmdline!r}"', source)
        self.assertIn("no process shares a GUI session pipe", source)

    def test_host_test_and_reset_have_distinct_stage7c4_names(self) -> None:
        host = HOST_TEST.read_text(encoding="utf-8")
        reset = RESET.read_text(encoding="utf-8")
        self_test = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c4-takeover-safety-reset"', host)
        self.assertIn("pia-bazzite-stage7c4-takeover-driver.py", host)
        self.assertIn("PEER-PIPE RETAINED-SESSION PROOF HOST TESTS PASSED", host)
        self.assertIn('RESET_UNIT="pia-bazzite-stage7c4-takeover-safety-reset"', reset)
        self.assertNotIn("sudo ", self_test)

    def test_stage7c4_is_documented(self) -> None:
        self.assertTrue(DOC.is_file())
        documentation = DOC.read_text(encoding="utf-8").lower()
        self.assertIn("excludes the probe process", documentation)
        self.assertIn("command-line text first", documentation)
        self.assertIn("distinct pipes paired", documentation)


if __name__ == "__main__":
    unittest.main()
