from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CRASH_STATE = ROOT / "pia_bazzite" / "kill_switch_crash_state.py"
GUI = ROOT / "pia_bazzite" / "gui.py"
HELPER_CORE = ROOT / "helper" / "pia_bazzite_kill_switch_helper" / "core.py"
CLIENT = ROOT / "pia_bazzite" / "kill_switch_client.py"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7a-self-test.sh"


class Stage7AStaticTests(unittest.TestCase):
    def test_recovery_record_cannot_change_firewall_or_networkmanager(self) -> None:
        source = CRASH_STATE.read_text(encoding="utf-8")
        for forbidden in (
            ".disable(",
            "emergency_reset",
            "subprocess",
            "nmcli",
            "nft ",
            "pkexec",
        ):
            self.assertNotIn(forbidden, source)

    def test_adoption_requires_exact_live_route_and_conservative_probes(self) -> None:
        source = CRASH_STATE.read_text(encoding="utf-8")
        self.assertIn("helper_status.physical_interfaces", source)
        self.assertIn("helper_status.endpoints", source)
        self.assertIn("active_profile != record.profile_uuid", source)
        self.assertIn("ipv4_tcp=True", source)
        self.assertIn("ipv6_tcp=True", source)
        self.assertIn("dns_tcp=True", source)
        self.assertIn("dns_udp=True", source)

    def test_storage_is_atomic_private_and_rejects_symlinks(self) -> None:
        source = CRASH_STATE.read_text(encoding="utf-8")
        self.assertIn("os.O_EXCL", source)
        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("os.replace", source)
        self.assertIn("os.fsync", source)
        self.assertIn("0o600", source)
        self.assertIn("stat.S_ISLNK", source)

    def test_helper_and_client_expose_exact_verified_allowlists(self) -> None:
        helper = HELPER_CORE.read_text(encoding="utf-8")
        client = CLIENT.read_text(encoding="utf-8")
        self.assertIn('"inspect-route"', helper)
        self.assertIn('"physical_interfaces"', helper)
        self.assertIn('"endpoints"', helper)
        self.assertIn('"inspect-route" not in capabilities', client)
        self.assertIn("physical_interfaces=physical_interfaces", client)
        self.assertIn("endpoints=endpoints", client)

    def test_stage7a_verifier_is_used_only_after_independent_live_status_reads(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _reconcile_kill_switch_startup(")
        end = source.index("    def _recheck_kill_switch_status(", start)
        method = source[start:end]
        self.assertIn("first_status = session.status()", method)
        self.assertIn("second_status = session.status()", method)
        self.assertIn("first_network = network_manager.connection_state()", method)
        self.assertIn("second_network = network_manager.connection_state()", method)
        self.assertLess(method.index("second_status = session.status()"), method.index("CrashRecoveryVerifier().evaluate("))

    def test_self_test_is_unprivileged_and_network_free(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "does not use sudo, pkexec, networking, NetworkManager, nftables, or the GUI",
            source,
        )
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec ", source)
        self.assertNotIn("systemd-run", source)


if __name__ == "__main__":
    unittest.main()
