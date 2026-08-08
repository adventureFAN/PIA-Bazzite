from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from pia_bazzite import network_manager
from pia_bazzite.network_manager import ConnectionState, NetworkManagerError


PROFILE = "11111111-1111-4111-8111-111111111111"


class NetworkManagerReconnectTests(unittest.TestCase):

    def test_active_state_query_failure_is_unknown_not_disconnected(self) -> None:
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager, "_run", side_effect=NetworkManagerError("t", "m")
        ) as run:
            with self.assertRaises(NetworkManagerError):
                network_manager.connection_state()
        self.assertNotEqual(run.call_args.kwargs.get("check"), False)

    def test_inactive_profile_query_failure_is_unknown_not_missing(self) -> None:
        with patch.object(
            network_manager, "_run", side_effect=NetworkManagerError("t", "m")
        ) as run:
            with self.assertRaises(NetworkManagerError):
                network_manager._profile_is_available(PROFILE)
        self.assertNotEqual(run.call_args.kwargs.get("check"), False)

    def test_disconnect_state_query_failure_raises_before_down(self) -> None:
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager, "connection_state", side_effect=NetworkManagerError("t", "m")
        ), patch.object(network_manager, "_run") as run:
            with self.assertRaises(NetworkManagerError):
                network_manager.disconnect()
        run.assert_not_called()

    def test_failed_down_uses_verified_state_not_localized_error_text(self) -> None:
        failed = subprocess.CompletedProcess(args=[], returncode=10, stdout="", stderr="not active")
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager, "connection_state", side_effect=[ConnectionState(True, PROFILE), ConnectionState(True, PROFILE)]
        ), patch.object(network_manager, "_run", return_value=failed):
            with self.assertRaises(NetworkManagerError):
                network_manager.disconnect(PROFILE)

    def test_invalid_uuid_is_rejected_before_nmcli(self) -> None:
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager, "_run"
        ) as run:
            with self.assertRaises(NetworkManagerError):
                network_manager.reconnect("profile; reboot")
        run.assert_not_called()

    def test_active_vpn_is_refused_before_profile_activation(self) -> None:
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager,
            "connection_state",
            return_value=ConnectionState(True, PROFILE),
        ), patch.object(network_manager, "_run") as run:
            with self.assertRaises(NetworkManagerError):
                network_manager.reconnect(PROFILE)
        run.assert_not_called()

    def test_missing_fixed_inactive_profile_is_refused(self) -> None:
        listing = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="22222222-2222-4222-8222-222222222222:Other:wireguard\n",
            stderr="",
        )
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager,
            "connection_state",
            return_value=ConnectionState(False),
        ), patch.object(network_manager, "_run", return_value=listing) as run:
            with self.assertRaises(NetworkManagerError):
                network_manager.reconnect(PROFILE)
        self.assertEqual(run.call_count, 1)

    def test_reconnect_uses_fixed_argv_and_verifies_same_uuid(self) -> None:
        listing = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{PROFILE}:PIA Bazzite:wireguard\n",
            stderr="",
        )
        activation = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        states = [ConnectionState(False), ConnectionState(True, PROFILE)]
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager,
            "connection_state",
            side_effect=states,
        ), patch.object(
            network_manager, "vpn_ipv4_route_active", return_value=True
        ), patch.object(
            network_manager,
            "_run",
            side_effect=[listing, activation],
        ) as run:
            result = network_manager.reconnect(PROFILE)
        self.assertEqual(result, PROFILE)
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["nmcli", "connection", "up", "uuid", PROFILE],
        )
        self.assertNotIn("shell", run.call_args_list[1].kwargs)

    def test_wrong_active_uuid_after_nmcli_is_rejected(self) -> None:
        listing = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{PROFILE}:PIA Bazzite:wireguard\n",
            stderr="",
        )
        activation = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        wrong = "33333333-3333-4333-8333-333333333333"
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager,
            "connection_state",
            side_effect=[ConnectionState(False), ConnectionState(True, wrong)],
        ), patch.object(
            network_manager,
            "_run",
            side_effect=[listing, activation],
        ):
            with self.assertRaises(NetworkManagerError):
                network_manager.reconnect(PROFILE)

    def test_ipv4_route_requires_fixed_pia_interface(self) -> None:
        selected = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="1.1.1.1 dev piabazzite src 10.0.0.2 uid 1000\n", stderr=""
        )
        with patch.object(network_manager.shutil, "which", return_value="/usr/sbin/ip"), patch.object(
            network_manager, "_run", return_value=selected
        ) as run:
            self.assertTrue(network_manager.vpn_ipv4_route_active())
        self.assertEqual(
            run.call_args.args[0],
            ["ip", "-4", "route", "get", network_manager.IPV4_PROBE_TARGET],
        )

    def test_ipv4_route_rejects_physical_interface(self) -> None:
        selected = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="1.1.1.1 via 192.0.2.1 dev wlo1 src 192.0.2.5 uid 1000\n", stderr=""
        )
        with patch.object(network_manager.shutil, "which", return_value="/usr/sbin/ip"), patch.object(
            network_manager, "_run", return_value=selected
        ):
            self.assertFalse(network_manager.vpn_ipv4_route_active())

    def test_profile_disables_tunnel_ipv6_and_leaves_containment_to_firewall_guard(self) -> None:
        source = __import__("pathlib").Path(network_manager.__file__).read_text(encoding="utf-8")
        self.assertIn('"ipv6.method", "disabled"', source)
        self.assertIn('"ipv6.never-default", "yes"', source)
        self.assertNotIn('type=blackhole', source)
        self.assertNotIn('ipv6_blackhole_active', source)
        self.assertGreaterEqual(source.count('if not vpn_ipv4_route_active():'), 2)



if __name__ == "__main__":
    unittest.main()
