from __future__ import annotations

import json
from pathlib import Path
import unittest

from pia_bazzite import __version__


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"
README = ROOT / "README.md"
RELEASE_NOTES = ROOT / f"RELEASE_NOTES_{__version__}.md"


class Stage8C3BFinalPolishTests(unittest.TestCase):
    def test_reset_copy_is_product_language_and_warns_about_real_ip(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))

        self.assertEqual(
            de["menu.emergency_reset"],
            "Kill-Switch-Schutz zurücksetzen…",
        )
        self.assertEqual(
            en["menu.emergency_reset"],
            "Reset Kill Switch Protection…",
        )
        self.assertNotIn("Emergency Reset", de["menu.emergency_reset"])
        self.assertNotIn("Notfall-Freigabe", de["menu.emergency_reset"])
        self.assertNotIn("Sicher blockiert", de["emergency_reset.confirm_message"])
        self.assertIn("ohne VPN-Schutz", de["emergency_reset.confirm_message"])
        self.assertIn("öffentliche IP-Adresse", de["emergency_reset.confirm_message"])
        self.assertIn("without VPN protection", en["emergency_reset.confirm_message"])
        self.assertIn("real public IP address", en["emergency_reset.confirm_message"])

    def test_reset_help_action_is_hidden_unless_a_disconnected_firewall_is_known(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        init = source[
            source.index("        self.emergency_reset_action = QAction(self)") :
            source.index("        self.english_action = QAction(self)")
        ]
        self.assertIn("self.emergency_reset_action.setVisible(False)", init)

        controls = source[
            source.index("    def _update_controls") :
            source.index("    def refresh_public_info", source.index("    def _update_controls"))
        ]
        relevant = controls[
            controls.index("        emergency_relevant = bool(") :
            controls.index("        self.emergency_reset_action.setEnabled", controls.index("        emergency_relevant = bool(")) + 100
        ]
        self.assertIn("self._kill_switch_status.present", relevant)
        self.assertIn("(not network_state_known or not connected)", relevant)
        self.assertIn("self.emergency_reset_action.setVisible(emergency_relevant)", relevant)
        self.assertNotIn("self.kill_switch_runtime.feature_enabled", relevant)

    def test_startup_recovery_failure_offers_retry_and_explicit_reset(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        method = source[
            source.index("    def _show_startup_recovery_failure") :
            source.index("    def _show_error", source.index("    def _show_startup_recovery_failure"))
        ]
        self.assertIn('tr("startup_recovery.retry")', method)
        self.assertIn('tr("menu.emergency_reset")', method)
        self.assertIn("QMessageBox.ButtonRole.AcceptRole", method)
        self.assertIn("QMessageBox.ButtonRole.ActionRole", method)
        self.assertIn("QTimer.singleShot(0, self._reconcile_kill_switch_startup)", method)
        self.assertIn("QTimer.singleShot(0, self.emergency_reset)", method)
        self.assertIn("if clicked is retry_button:", method)
        self.assertIn("elif clicked is reset_button:", method)

        recovery = source[
            source.index("    def _reconcile_kill_switch_startup") :
            source.index("    def _recheck_kill_switch_status")
        ]
        self.assertGreaterEqual(
            recovery.count("self._show_startup_recovery_failure("),
            4,
        )

    def test_polkit_cancellation_has_neutral_safe_user_path(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        helper = source[
            source.index("    def _authorization_denied_in_chain") :
            source.index("    def _show_startup_recovery_failure")
        ]
        self.assertIn("AuthorizationDeniedError", helper)
        self.assertIn("QMessageBox.Icon.Information", helper)
        self.assertIn('tr("authorization.not_granted.title")', helper)
        self.assertIn('tr("authorization.not_granted.message")', helper)

        self.assertGreaterEqual(
            source.count("authorization_cancel_safe=True"),
            2,
        )

        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertIn("VPN und Kill-Switch-Firewall blieben unverändert", de["authorization.not_granted.message"])
        self.assertIn("VPN and Kill Switch firewall remained unchanged", en["authorization.not_granted.message"])

    def test_server_refresh_wording_and_ipv6_tooltip_wrap_are_polished(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(de["connection.reload"], "Serverliste aktualisieren")
        self.assertEqual(en["connection.reload"], "Refresh server list")
        self.assertGreaterEqual(de["tooltip.ipv6"].count("\n"), 2)
        self.assertGreaterEqual(en["tooltip.ipv6"].count("\n"), 2)
        self.assertLessEqual(max(map(len, de["tooltip.ipv6"].splitlines())), 80)
        self.assertLessEqual(max(map(len, en["tooltip.ipv6"].splitlines())), 80)

    def test_public_release_docs_describe_reset_consequence(self) -> None:
        readme = README.read_text(encoding="utf-8")
        notes = RELEASE_NOTES.read_text(encoding="utf-8")
        self.assertIn("Reset Kill Switch Protection", readme)
        self.assertIn("real public IP address may be visible", readme)
        self.assertIn("Reset Kill Switch Protection", notes)
        self.assertIn("real public IP address may be visible", notes)


if __name__ == "__main__":
    unittest.main()
