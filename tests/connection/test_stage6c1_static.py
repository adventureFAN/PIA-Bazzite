from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tools" / "pia-bazzite-stage6c1-gui-sentinel-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-recovery-stage6c1-gui-sentinel-test.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-recovery-stage6c1-self-test.sh"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage6C1StaticTests(unittest.TestCase):
    def test_gui_sentinel_driver_orders_baseline_lock_loss_reconnect_switch_and_stop(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        baseline = source.index("sentinel.prove_direct_baseline()")
        app_launch = source.index("app_process = subprocess.Popen(", baseline)
        initial = source.index("old_uuid = _wait_for_initial_protection(", app_launch)
        forced_loss = source.index("reconnected_uuid = _force_and_wait_for_reconnect(", initial)
        switch = source.index("_new_uuid, _new_ip = _wait_for_server_switch(", forced_loss)
        stop = source.index("sentinel.stop_and_assert_clean()", switch)
        disconnect = source.index("_wait_for_deliberate_disconnect(", stop)
        self.assertLess(baseline, app_launch)
        self.assertLess(app_launch, initial)
        self.assertLess(initial, forced_loss)
        self.assertLess(forced_loss, switch)
        self.assertLess(switch, stop)
        self.assertLess(stop, disconnect)

    def test_sentinel_starts_only_after_verified_production_table_appears(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("def _wait_for_initial_protection(")
        end = source.index("def _force_and_wait_for_reconnect(", start)
        method = source[start:end]
        self.assertIn("if present and not verified:", method)
        self.assertIn("if present and verified and not sentinel_started:", method)
        self.assertIn("sentinel.start()", method)
        self.assertLess(
            method.index("if present and verified and not sentinel_started:"),
            method.index("sentinel.start()"),
        )

    def test_reconnect_and_switch_require_verified_lock_and_clean_sentinel(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        reconnect_start = source.index("def _force_and_wait_for_reconnect(")
        switch_start = source.index("def _wait_for_server_switch(", reconnect_start)
        disconnect_start = source.index("def _wait_for_deliberate_disconnect(", switch_start)
        reconnect = source[reconnect_start:switch_start]
        switch = source[switch_start:disconnect_start]
        self.assertIn('_require_verified_lock(nft_path, "the GUI automatic reconnect")', reconnect)
        self.assertIn('sentinel.assert_running_and_clean("the GUI automatic reconnect")', reconnect)
        self.assertIn("network_manager.disconnect(profile_uuid)", reconnect)
        self.assertIn('_require_verified_lock(nft_path, "the GUI protected server switch")', switch)
        self.assertIn('sentinel.assert_running_and_clean("the GUI protected server switch")', switch)
        self.assertIn("state.uuid != old_profile_uuid", switch)

    def test_real_driver_never_opens_or_destroys_the_firewall(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertNotIn("session.disable(", source)
        self.assertNotIn("destroy table", source)
        self.assertNotIn("emergency_reset", source)
        self.assertNotIn("shell=True", source)
        self.assertIn("FirewallExpectedFailure", source)
        self.assertIn("self.lock_observed = True", source)
        self.assertIn("or sentinel.lock_observed", source)

    def test_host_wrapper_arms_reset_before_real_gui_driver(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        timer = source.index("sudo systemd-run")
        driver = source.index('"$ROOT/tools/pia-bazzite-stage6c1-gui-sentinel-driver.py"')
        self.assertLess(timer, driver)
        self.assertIn("/usr/bin/nmcli connection down id 'PIA Bazzite'", source)
        self.assertIn("destroy table inet", source)
        self.assertIn("FAIL-CLOSED STOP", source)

    def test_gui_driver_requires_saved_live_log_before_success(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn('"pia-stage6c1-gui-sentinel-live-log.txt"', source)
        self.assertIn("LIVE_LOG_PATH.stat()", source)
        self.assertIn("stat.st_mtime < test_started_wallclock", source)
        self.assertIn("GUI Live Log was saved", source)

    def test_security_log_wording_is_explicit_and_translation_sets_match(self) -> None:
        de = json.loads(DE.read_text(encoding="utf-8"))
        en = json.loads(EN.read_text(encoding="utf-8"))
        self.assertEqual(set(de), set(en))
        self.assertEqual(
            de["log.kill_switch.preference.enabling"],
            "Die Systemberechtigung für den Kill Switch wird angefordert und der sichere Ausgangszustand geprüft.",
        )
        self.assertEqual(
            de["log.kill_switch.connection.authorization"],
            "Die Systemberechtigung für die eingeschränkte Kill-Switch-Sitzung wird angefordert.",
        )
        self.assertIn("die Sperre bleibt aktiv", de["log.kill_switch.recovery.firewall_updating"])
        self.assertNotIn("Der Kill Switch wird freigegeben", de.values())
        self.assertNotIn("Kill-Switch-Freigabe", de.values())

    def test_self_test_is_unprivileged_and_does_not_start_real_gui_test(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, the GUI, or the leak sentinel",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("stage6c1-gui-sentinel-test.sh\" \"$@", source)
        self.assertNotIn("./run.sh", source)


if __name__ == "__main__":
    unittest.main()
