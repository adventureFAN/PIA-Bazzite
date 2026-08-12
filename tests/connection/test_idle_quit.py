from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"


class IdleQuitRegressionTests(unittest.TestCase):
    def _method(self, source: str, name: str, next_name: str) -> str:
        start = source.index(f"    def {name}(")
        end = source.index(f"    def {next_name}(", start)
        return source[start:end]

    def test_clean_disconnected_quit_uses_existing_recovery_gate(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        method = self._method(source, "request_quit", "_final_quit")

        self.assertIn(
            "if self._disconnected_kill_switch_may_block(connected=False):",
            method,
        )
        self.assertIn("self._recheck_kill_switch_status(", method)
        self.assertIn("after_absent=self._final_quit", method)
        self.assertNotIn("self._kill_switch_status is None", method)

    def test_recovery_gate_still_treats_real_or_ambiguous_lock_as_blocking(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        method = self._method(
            source,
            "_disconnected_kill_switch_may_block",
            "_networkmanager_unknown_view_state",
        )

        self.assertIn("if connected or not self.kill_switch_runtime.feature_enabled:", method)
        self.assertIn("if self._kill_switch_status_error:", method)
        self.assertIn("return True", method)
        self.assertIn("return self._kill_switch_status.present", method)
        self.assertIn("return self._startup_kill_switch_reconciliation_required()", method)

    def test_disabling_kill_switch_still_checks_privileged_host_state(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        method = self._method(
            source,
            "_disable_kill_switch_preference",
            "_friendly_kill_switch_error",
        )

        self.assertIn("KillSwitchSessionClient(timeout=120.0)", method)
        self.assertIn("session.open()", method)
        self.assertIn("status = session.status()", method)


if __name__ == "__main__":
    unittest.main()
