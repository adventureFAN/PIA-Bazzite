from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
NM = ROOT / "pia_bazzite" / "network_manager.py"
LIFECYCLE = ROOT / "pia_bazzite" / "ipv6_guard_lifecycle.py"
HELPER_CLI = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "cli.py"
DEBUG = ROOT / "tools" / "pia-bazzite-network-debug.sh"
RUNTIME_CHECK = ROOT / "tools" / "pia-bazzite-ipv6-guard-runtime-check.sh"
KS_HOST_PREFLIGHT = ROOT / "tools" / "kill-switch-host-preflight.sh"
HANDOFF = ROOT / "docs" / "HANDOFF.md"
README = ROOT / "README.md"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"


class Stage8C3A7IPv6GuardIntegrationTests(unittest.TestCase):
    def test_networkmanager_no_longer_claims_route_only_ipv6_containment(self) -> None:
        source = NM.read_text(encoding="utf-8")
        self.assertIn('"ipv6.method", "disabled"', source)
        self.assertIn('"ipv6.never-default", "yes"', source)
        self.assertIn("def vpn_ipv4_route_active()", source)
        self.assertIn('fields.index("dev")', source)
        self.assertIn('INTERFACE_NAME', source)
        self.assertNotIn("type=blackhole", source)
        self.assertNotIn("ipv6_blackhole_active", source)

    def test_normal_connect_uses_guard_lifecycle_and_persists_recovery_intent(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def connect_region(")
        end = source.index("    def _schedule_protected_reconnect(", start)
        method = source[start:end]
        gate = method.index("_ensure_packaged_kill_switch_helper(")
        marker = method.index("self._set_ipv6_guard_expected(True)")
        lifecycle = method.index("IPv6GuardLifecycle(")
        self.assertLess(gate, lifecycle)
        self.assertLess(marker, lifecycle)
        self.assertIn("result = lifecycle.connect(config_path)", method)
        self.assertIn("self._set_cached_ipv6_guard_status(result.status)", method)
        self.assertIn('self.log("ok", "log.ipv6_guard.armed")', method)

    def test_normal_disconnect_is_vpn_first_guard_second_through_lifecycle(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def disconnect(")
        end = source.index("    def _disconnected_kill_switch_may_block(", start)
        method = source[start:end]
        self.assertIn("result = lifecycle.disconnect(profile_uuid)", method)
        self.assertIn("self._set_ipv6_guard_expected(False)", method)
        self.assertIn('self.log("ok", "log.ipv6_guard.released")', method)

        lifecycle_source = LIFECYCLE.read_text(encoding="utf-8")
        start2 = lifecycle_source.index("    def disconnect(")
        end2 = lifecycle_source.index("    def release_after_verified_vpn_loss(", start2)
        disconnect = lifecycle_source[start2:end2]
        vpn_down = disconnect.index("self.vpn_backend.disconnect(profile_uuid)")
        vpn_verify = disconnect.index("self.vpn_backend.is_connected()", vpn_down)
        guard_disable = disconnect.index("self.session.ipv6_guard_disable()", vpn_verify)
        self.assertLess(vpn_down, vpn_verify)
        self.assertLess(vpn_verify, guard_disable)

    def test_unexpected_loss_and_startup_keep_guard_fail_safe(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("_release_ipv6_guard_after_unexpected_vpn_loss", source)
        self.assertIn("_reconcile_ipv6_guard_startup", source)
        self.assertIn("connection/ipv6_guard_expected", source)
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn('disposition="adopted-connected"', lifecycle)
        self.assertIn('disposition="cleared-stale-guard"', lifecycle)
        self.assertIn('disposition="stopped-unprotected-vpn"', lifecycle)
        self.assertIn("Refusing to release the IPv6 guard while the PIA VPN is still active", lifecycle)

    def test_full_and_small_firewalls_are_mutually_exclusive_at_privileged_boundary(self) -> None:
        source = HELPER_CLI.read_text(encoding="utf-8")
        self.assertIn('args.action == "ipv6-guard-enable" and runner.table_exists(TABLE_NAME)', source)
        self.assertIn('args.action == "enable" and runner.table_exists(IPV6_GUARD_TABLE_NAME)', source)
        gui = GUI.read_text(encoding="utf-8")
        start = gui.index("    def _authorize_kill_switch_preference(")
        end = gui.index("    def _disable_kill_switch_preference(", start)
        method = gui[start:end]
        self.assertIn("if network_manager.is_connected():", method)
        self.assertIn("guard = session.ipv6_guard_status()", method)
        self.assertIn("guard = session.ipv6_guard_disable()", method)
        self.assertIn("self._set_ipv6_guard_expected(False)", method)

    def test_diagnostics_describe_firewall_guard_not_blackhole_as_current_behavior(self) -> None:
        debug = DEBUG.read_text(encoding="utf-8")
        self.assertIn("IPv6-only nftables guard", debug)
        self.assertIn("IPv6 route may still name the physical interface", debug)
        self.assertNotIn("low-metric blackhole", debug)
        preflight = KS_HOST_PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("no NetworkManager blackhole route is required", preflight)
        self.assertNotIn("expected IPv6 blackhole route", preflight)
        runtime = RUNTIME_CHECK.read_text(encoding="utf-8")
        self.assertIn("pia_bazzite_ipv6_guard", runtime)
        self.assertIn("pia-bazzite:ipv6-guard:v1:block-ipv6", runtime)
        for forbidden in (
            "nft add ",
            "nft delete ",
            "nft flush ",
            "nmcli connection up",
            "nmcli connection down",
            "nmcli connection modify",
        ):
            self.assertNotIn(forbidden, runtime)

    def test_public_copy_and_handoff_state_the_current_architecture(self) -> None:
        readme = README.read_text(encoding="utf-8")
        self.assertIn("IPv6-only firewall protection", readme)
        self.assertNotIn("Temporary IPv6 blackhole protection", readme)
        handoff = HANDOFF.read_text(encoding="utf-8")
        self.assertIn("Stage 8C.3A.7 normal-VPN IPv6 guard lifecycle integration candidate", handoff)
        self.assertIn("25 PASS, 0", handoff)
        self.assertIn("ALL STAGE-8C.3 IPV6 GUARD HELPER NAMESPACE", handoff)
        self.assertIn("not an RC", handoff)

    def test_translations_use_generic_protection_component_and_firewall_ipv6_copy(self) -> None:
        en = json.loads(EN.read_text(encoding="utf-8"))
        de = json.loads(DE.read_text(encoding="utf-8"))
        self.assertEqual(set(en), set(de))
        self.assertIn("IPv6-only guard", en["kill_switch.helper_install.install_message"])
        self.assertIn("IPv6-Sicherung", de["kill_switch.helper_install.install_message"])
        self.assertIn("firewall", en["tooltip.ipv6"].casefold())
        self.assertIn("firewall", de["tooltip.ipv6"].casefold())
        self.assertNotIn("blackhole", en["tooltip.ipv6"].casefold())
        self.assertNotIn("blackhole", de["tooltip.ipv6"].casefold())


if __name__ == "__main__":
    unittest.main()
