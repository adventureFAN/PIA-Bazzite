from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "pia_bazzite" / "kill_switch_connection.py"
GUI = ROOT / "pia_bazzite" / "gui.py"
SELF_TEST = ROOT / "tools" / "kill-switch-connection-stage5a-self-test.sh"
PREVIEW = ROOT / "tools" / "pia-bazzite-stage4c-runtime-preview.py"


class Stage5AStaticTests(unittest.TestCase):
    def test_orchestrator_has_no_gui_networkmanager_or_pia_api_import(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        for forbidden in (
            "PySide6",
            "from .network_manager",
            "from .pia_api",
            "subprocess",
            "requests",
            "nft",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_vpn_start_occurs_only_after_verified_enable(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertLess(
            source.index("firewall_status = self._prepare_firewall(plan)"),
            source.index("self.vpn_backend.connect(plan.config_path)"),
        )
        self.assertIn("_require_verified_active_status(status, action=\"enable\")", source)

    def test_failure_paths_never_disable_the_firewall(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        rollback = source[
            source.index("    def _rollback_after_postcheck_failure("):
            source.index("    def _disconnect_vpn_and_verify(")
        ]
        self.assertNotIn("self.session.disable", rollback)
        self.assertNotIn("emergency_reset", rollback)

    def test_stage5a_explicitly_defers_connected_server_switches(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("ServerSwitchDeferredError", source)
        self.assertIn("vpn_connected_before", source)

    def test_preview_menu_escapes_and_smoke_tests_literal_ampersand(self) -> None:
        gui_source = GUI.read_text(encoding="utf-8")
        preview_source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn('tr(state.title_key).replace("&", "&&")', gui_source)
        self.assertIn('expected_armed_menu = tr("kill_switch.state.armed").replace("&", "&&")', preview_source)

    def test_self_test_declares_no_privileged_or_network_actions(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn("does not use sudo, pkexec, networking, NetworkManager, or nftables", source)
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)


if __name__ == "__main__":
    unittest.main()
