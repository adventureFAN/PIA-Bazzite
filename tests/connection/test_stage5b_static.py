from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "core.py"
CLI = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "cli.py"
INSTALLED_ENTRY = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "installed_entry.py"
SESSION_ENTRY = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "session_entry.py"
INSTALLED_SESSION = ROOT / "helper" / "pia-bazzite-kill-switch-session-installed"
CLIENT = ROOT / "pia_bazzite" / "kill_switch_client.py"
ORCHESTRATOR = ROOT / "pia_bazzite" / "kill_switch_connection.py"
NETWORK_PATHS = ROOT / "pia_bazzite" / "network_paths.py"
HOST_DRIVER = ROOT / "tools" / "pia-bazzite-stage5b-host-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-connection-stage5b-host-test.sh"
EMERGENCY_RESET = ROOT / "tools" / "kill-switch-connection-stage5b-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-connection-stage5b-self-test.sh"


class Stage5BStaticTests(unittest.TestCase):
    def test_production_helper_identity_is_consistent(self) -> None:
        core = CORE.read_text(encoding="utf-8")
        client = CLIENT.read_text(encoding="utf-8")
        self.assertIn('HELPER_STAGE = 5', core)
        self.assertIn('TABLE_NAME = "pia_bazzite_killswitch"', core)
        self.assertIn('EXPECTED_HELPER_STAGE = 5', client)
        self.assertNotIn('pia_bazzite_killswitch_helper_test', core)

    def test_direct_project_helper_still_refuses_host_namespace(self) -> None:
        cli = CLI.read_text(encoding="utf-8")
        self.assertIn('trusted_host: bool = False', cli)
        self.assertIn('if not trusted_host:', cli)
        self.assertIn('_require_isolated_network_namespace()', cli)
        self.assertIn('Host operation is allowed only through the verified installed launcher.', cli)

    def test_only_verified_installed_boundaries_enable_host_operation(self) -> None:
        installed_entry = INSTALLED_ENTRY.read_text(encoding="utf-8")
        session_entry = SESSION_ENTRY.read_text(encoding="utf-8")
        installed_session = INSTALLED_SESSION.read_text(encoding="utf-8")
        self.assertIn('helper_main(raw_argv, trusted_host=True)', installed_entry)
        self.assertIn('def main(*, trusted_host: bool = False)', session_entry)
        self.assertIn('session_main(trusted_host=True)', installed_session)

    def test_intentional_disconnect_is_fail_closed_until_verified_unlock(self) -> None:
        source = ORCHESTRATOR.read_text(encoding="utf-8")
        start = source.index('    def disconnect_intentionally(')
        end = source.index('    def _prepare_firewall(', start)
        method = source[start:end]
        protected = method[method.index('ConnectionPhase.DISCONNECT_PREFLIGHT_STARTED') :]
        self.assertLess(protected.index('active_status = self.session.status()'), protected.index('self._disconnect_vpn_and_verify('))
        self.assertLess(protected.index('blocked_path_probe()'), protected.index('disabled_status = self.session.disable()'))
        self.assertIn('_require_verified_disabled_status(disabled_status, action="disable")', method)

    def test_host_driver_prepares_exact_route_before_firewall_session(self) -> None:
        source = HOST_DRIVER.read_text(encoding="utf-8")
        self.assertLess(source.index('sys.path.insert(0, str(ROOT))'), source.index('from pia_bazzite import network_manager'))
        self.assertLess(source.index('endpoint = read_wireguard_endpoint(config_path)'), source.index('session.open()'))
        self.assertLess(source.index('interface = discover_physical_interface(endpoint)'), source.index('session.open()'))
        self.assertIn('not _probe_dns_udp(IPV4_TEST_ADDRESS, 4.0)', source)
        self.assertIn('blocked_path_probe=blocked_path_probe', source)
        self.assertNotIn('shell=True', source)

    def test_route_discovery_uses_numeric_endpoint_without_shell(self) -> None:
        source = NETWORK_PATHS.read_text(encoding="utf-8")
        self.assertIn('ipaddress.ip_address(host)', source)
        self.assertIn('"route", "get", host', source)
        self.assertIn('shell=False', source)
        self.assertIn('if interface in {"lo", VPN_INTERFACE_NAME}', source)

    def test_independent_reset_is_armed_before_real_driver(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        self.assertLess(source.index('sudo systemd-run'), source.index('pia-bazzite-stage5b-host-driver.py'))
        self.assertIn('--on-active="$RESET_DELAY"', source)
        self.assertIn('pia_bazzite_killswitch', source)
        self.assertIn('cancel_reset_timer', source)

    def test_emergency_reset_stops_vpn_before_removing_table(self) -> None:
        source = EMERGENCY_RESET.read_text(encoding="utf-8")
        self.assertLess(source.index("nmcli connection down id 'PIA Bazzite'"), source.index('destroy table inet "$TABLE"'))
        self.assertIn('list table inet "$TABLE"', source)

    def test_self_test_never_executes_host_actions(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn('does not use sudo, pkexec, networking, NetworkManager, or nftables', source)
        self.assertNotIn('sudo ', source)
        self.assertNotIn('pkexec ', source)
        self.assertNotIn('stage5b-host-driver.py" "$@"', source)


if __name__ == "__main__":
    unittest.main()
