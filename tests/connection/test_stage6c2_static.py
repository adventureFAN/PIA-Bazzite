from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
SINGLE_INSTANCE = ROOT / "pia_bazzite" / "single_instance.py"
DRIVER = ROOT / "tools" / "pia-bazzite-stage6c1-gui-sentinel-driver.py"
PREFLIGHT = ROOT / "tools" / "pia-bazzite-stage6c2-instance-preflight.py"
HOST_TEST = ROOT / "tools" / "kill-switch-recovery-stage6c2-gui-sentinel-test.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-recovery-stage6c2-self-test.sh"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage6C2StaticTests(unittest.TestCase):
    def test_emergency_reset_recheck_is_read_only_and_uses_fixed_client_status(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _recheck_kill_switch_status(")
        end = source.index("    def emergency_reset(", start)
        method = source[start:end]
        self.assertIn("KillSwitchClient(timeout=120.0).status()", method)
        self.assertNotIn(".disable(", method)
        self.assertNotIn("emergency_reset", method)
        self.assertNotIn("session.enable", method)
        self.assertIn("if outcome.status.present:", method)
        self.assertIn("self._kill_switch_probe_baseline = None", method)
        self.assertIn("self._kill_switch_route_plan = None", method)

    def test_quit_rechecks_host_state_before_allowing_close(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def request_quit(")
        end = source.index("    def _final_quit(", start)
        method = source[start:end]
        call = method.index("self._recheck_kill_switch_status(")
        callback = method.index("after_absent=self._final_quit", call)
        self.assertLess(call, callback)
        self.assertNotIn("refuses to close while the production firewall", method)

    def test_stale_or_unowned_lock_offers_status_recheck_not_invalid_reconnect(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        toggle_start = source.index("    def toggle_connection(")
        toggle_end = source.index("    def connect_region(", toggle_start)
        toggle = source[toggle_start:toggle_end]
        self.assertIn("self._protected_reconnect_context_available()", toggle)
        self.assertIn("self._recheck_kill_switch_status()", toggle)
        self.assertIn('"connection.recheck_protection"', source)

    def test_instance_probe_requires_live_socket_and_never_removes_it(self) -> None:
        source = SINGLE_INSTANCE.read_text(encoding="utf-8")
        start = source.index("def instance_is_running(")
        end = source.index("class SingleInstance", start)
        probe = source[start:end]
        self.assertIn("waitForConnected", probe)
        self.assertNotIn("removeServer", probe)
        self.assertNotIn('write(b"activate")', probe)

    def test_real_gui_host_test_refuses_an_existing_app_before_sudo(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        preflight = source.index("pia-bazzite-stage6c2-instance-preflight.py")
        sudo = source.index("sudo -v")
        timer = source.index("sudo systemd-run")
        self.assertLess(preflight, sudo)
        self.assertLess(preflight, timer)
        self.assertTrue(PREFLIGHT.is_file())

    def test_driver_rechecks_single_instance_immediately_before_launch(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        launch = source.index("app_process = subprocess.Popen(")
        before = source.rfind("instance_is_running(__app_id__", 0, launch)
        self.assertGreater(before, 0)
        self.assertLess(before, launch)

    def test_recovery_wording_is_explicit_and_translation_sets_match(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))
        self.assertEqual(de["connection.recheck_protection"], "Schutzstatus neu prüfen")
        self.assertIn("ausschließlich lesend", de["log.kill_switch.status_recheck.started"])
        self.assertIn("nicht automatisch verändert", de["log.kill_switch.status_recheck.present"])

    def test_self_test_is_unprivileged_and_does_not_start_gui_or_instance_probe(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn("does not use sudo, pkexec, networking, NetworkManager, nftables, the GUI, or the leak sentinel", source)
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("stage6c1-gui-sentinel-test.sh" "$@", source)


if __name__ == "__main__":
    unittest.main()
