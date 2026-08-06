from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from pia_bazzite import network_manager
from pia_bazzite.network_manager import ConnectionState, NetworkManagerError


PROFILE = "11111111-1111-4111-8111-111111111111"


class NetworkManagerReconnectTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
