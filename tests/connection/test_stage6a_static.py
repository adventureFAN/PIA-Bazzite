from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RECOVERY = ROOT / "pia_bazzite" / "kill_switch_recovery.py"
NETWORK_MANAGER = ROOT / "pia_bazzite" / "network_manager.py"
GUI = ROOT / "pia_bazzite" / "gui.py"
SELF_TEST = ROOT / "tools" / "kill-switch-recovery-stage6a-self-test.sh"


class Stage6AStaticTests(unittest.TestCase):
    def test_recovery_boundary_never_disables_or_emergency_resets_firewall(self) -> None:
        source = RECOVERY.read_text(encoding="utf-8")
        self.assertNotIn(".disable(", source)
        self.assertNotIn("emergency_reset", source)
        self.assertIn("the firewall table was not deliberately disabled", source)

    def test_reconnect_proves_blocked_path_before_nm_profile_reactivation(self) -> None:
        source = RECOVERY.read_text(encoding="utf-8")
        start = source.index("    def reconnect(")
        end = source.index("    def switch_server(", start)
        method = source[start:end]
        self.assertLess(
            method.index("self._open_and_verify_lock"),
            method.index("self._prove_blocked_path"),
        )
        self.assertLess(
            method.index("self._prove_blocked_path"),
            method.index("self._retarget_firewall"),
        )
        self.assertLess(
            method.index("self._retarget_firewall"),
            method.index("self.vpn_backend.reconnect"),
        )

    def test_server_switch_stops_old_vpn_and_proves_block_before_new_route(self) -> None:
        source = RECOVERY.read_text(encoding="utf-8")
        start = source.index("    def switch_server(")
        end = source.index("    def _open_and_verify_lock", start)
        method = source[start:end]
        old_down = method.index("self.vpn_backend.disconnect(current_profile)")
        blocked = method.index("self._prove_blocked_path", old_down)
        resolve = method.index("physical_interface_resolver(candidate.endpoint)")
        retarget = method.index("self._retarget_firewall(", resolve)
        new_connect = method.index("self.vpn_backend.connect(new_plan.config_path)")
        self.assertLess(old_down, blocked)
        self.assertLess(blocked, resolve)
        self.assertLess(resolve, retarget)
        self.assertLess(retarget, new_connect)

    def test_switch_firewall_transition_uses_union_then_exact_new_route(self) -> None:
        source = RECOVERY.read_text(encoding="utf-8")
        start = source.index("    def _retarget_firewall(")
        end = source.index("    def _verify_postconnect", start)
        method = source[start:end]
        union_interfaces = method.index("self.session.set_interfaces(union_interfaces)")
        union_endpoints = method.index("self.session.set_endpoints(union_endpoints)")
        exact_endpoints = method.index(
            "self.session.set_endpoints(target.endpoints)",
            union_endpoints,
        )
        exact_interfaces = method.index(
            "self.session.set_interfaces(target.physical_interfaces)",
            exact_endpoints,
        )
        self.assertLess(union_interfaces, union_endpoints)
        self.assertLess(union_endpoints, exact_endpoints)
        self.assertLess(exact_endpoints, exact_interfaces)

    def test_networkmanager_reconnect_accepts_only_uuid_and_fixed_argv(self) -> None:
        source = NETWORK_MANAGER.read_text(encoding="utf-8")
        start = source.index("def reconnect(")
        end = source.index("def disconnect(", start)
        method = source[start:end]
        self.assertIn("_normalize_profile_uuid(profile_uuid)", method)
        self.assertIn('["nmcli", "connection", "up", "uuid", profile]', method)
        self.assertNotIn("shell=True", method)
        self.assertNotIn("os.system", method)

    def test_stage6c_activates_the_tested_recovery_boundary_in_the_gui(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("KillSwitchRecoveryOrchestrator", source)
        self.assertIn("orchestrator.reconnect(", source)
        self.assertIn("orchestrator.switch_server(", source)

    def test_self_test_is_unprivileged_and_network_free(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, or nftables",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("./run.sh", source)


if __name__ == "__main__":
    unittest.main()
