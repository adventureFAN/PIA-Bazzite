from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tools" / "pia-bazzite-stage6b-host-driver.py"
SENTINEL = ROOT / "tools" / "pia-bazzite-stage6b-leak-sentinel.py"
HOST_TEST = ROOT / "tools" / "kill-switch-recovery-stage6b-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-recovery-stage6b-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-recovery-stage6b-self-test.sh"
GUI = ROOT / "pia_bazzite" / "gui.py"


class Stage6BStaticTests(unittest.TestCase):
    def test_real_driver_orders_loss_reconnect_switch_and_deliberate_unlock(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        initial_connect = source.index("connected = connection.connect(")
        sentinel_start = source.index("sentinel.start()", initial_connect)
        forced_loss = source.index("network_manager.disconnect(profile_uuid)", sentinel_start)
        reconnect = source.index("reconnected = recovery.reconnect(", forced_loss)
        prepare_candidate = source.index("create_wireguard_config(", reconnect)
        switch = source.index("switched = recovery.switch_server(", prepare_candidate)
        final_disconnect = source.index("disconnected = connection.disconnect_intentionally(", switch)
        self.assertLess(initial_connect, sentinel_start)
        self.assertLess(sentinel_start, forced_loss)
        self.assertLess(forced_loss, reconnect)
        self.assertLess(reconnect, prepare_candidate)
        self.assertLess(prepare_candidate, switch)
        self.assertLess(switch, final_disconnect)

    def test_final_probe_stops_and_verifies_sentinel_before_deliberate_unlock(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("            def final_blocked_probe()")
        end = source.index("            disconnected = connection.disconnect_intentionally(", start)
        closure = source[start:end]
        self.assertLess(
            closure.index("_blocked_probe"),
            closure.index("sentinel.stop_and_assert_clean()"),
        )
        self.assertIn("blocked_path_probe=final_blocked_probe", source)

    def test_failure_paths_do_not_directly_disable_or_reset_firewall(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertNotIn("session.disable(", source)
        self.assertNotIn("emergency_reset(", source)
        self.assertNotIn("nft ", source)
        self.assertIn("EXIT_FIREWALL_RETAINED", source)

    def test_switch_region_must_use_a_distinct_numeric_server(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("def _select_switch_region(")
        end = source.index("def _require_initial_disabled", start)
        method = source[start:end]
        self.assertIn("region.region_id != initial.region_id", method)
        self.assertIn("region.wireguard_ip != initial.wireguard_ip", method)
        self.assertIn("candidate.endpoint == initial_endpoint", source)

    def test_sentinel_has_fixed_targets_and_rejects_arbitrary_paths(self) -> None:
        source = SENTINEL.read_text(encoding="utf-8")
        self.assertIn('IPV4_TEST_ADDRESS = "1.1.1.1"', source)
        self.assertIn('IPV6_TEST_ADDRESS = "2606:4700:4700::1111"', source)
        self.assertIn("SO_BINDTODEVICE", source)
        self.assertIn("Sentinel paths must use the fixed Stage-6B /tmp prefix", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("subprocess", source)


    def test_sentinel_publishes_user_owned_atomic_results(self) -> None:
        source = SENTINEL.read_text(encoding="utf-8")
        self.assertIn('os.environ.get("SUDO_UID", "")', source)
        self.assertIn('os.environ.get("SUDO_GID", "")', source)
        self.assertIn("os.fchown(descriptor, owner_uid, owner_gid)", source)
        self.assertLess(
            source.index("os.fchown(descriptor, owner_uid, owner_gid)"),
            source.index("os.replace(temporary, path)"),
        )

    def test_driver_refuses_stale_baseline_result_before_monitoring(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        baseline_cleanup = source.index('self._assert_no_stale_files("after the direct baseline")')
        monitor_start = source.index("self.process = subprocess.Popen(", baseline_cleanup)
        self.assertLess(baseline_cleanup, monitor_start)
        self.assertIn("refusing to read an old sample", source)

    def test_immediate_leak_branch_cannot_print_a_contradictory_clean_result(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index('if bool(payload.get("leak_detected")):', source.index("def start(self)"))
        end = source.index('print(', start)
        branch = source[start:end]
        self.assertIn("self.stop_without_assertion()", branch)
        self.assertNotIn("self.stop_and_assert_clean()", branch)
        self.assertIn("DIRECT FALLBACK DETECTED immediately", branch)

    def test_host_wrapper_arms_reset_before_real_driver(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        timer = source.index("sudo systemd-run")
        driver = source.index('"$ROOT/tools/pia-bazzite-stage6b-host-driver.py"')
        self.assertLess(timer, driver)
        self.assertIn("/usr/bin/nmcli connection down id 'PIA Bazzite'", source)
        self.assertIn("destroy table inet", source)
        self.assertIn("FAIL-CLOSED STOP", source)

    def test_emergency_reset_stops_vpn_before_destroying_fixed_table(self) -> None:
        source = RESET.read_text(encoding="utf-8")
        stop = source.index("nmcli connection down id 'PIA Bazzite'")
        destroy = source.index('destroy table inet "$TABLE"')
        self.assertLess(stop, destroy)
        self.assertIn('TABLE="pia_bazzite_killswitch"', source)

    def test_stage6c_uses_the_real_host_tested_recovery_calls(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("KillSwitchRecoveryOrchestrator", source)
        self.assertIn("blocked_path_probe=baseline.ordinary_path_is_blocked", source)
        self.assertIn("physical_interface_resolver=resolve_existing_physical_interface", source)

    def test_self_test_is_unprivileged_and_never_runs_real_host_tools(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, or the leak sentinel",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("stage6b-host-test.sh\" \"$@", source)


if __name__ == "__main__":
    unittest.main()
