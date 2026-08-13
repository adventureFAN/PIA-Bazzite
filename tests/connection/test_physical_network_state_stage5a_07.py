from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from pia_bazzite import network_manager


class Stage5APhysicalNetworkStateTests(unittest.TestCase):
    def test_connected_wifi_counts_as_physical_underlay(self) -> None:
        output = """GENERAL.DEVICE:wlo1
GENERAL.TYPE:wifi
GENERAL.STATE:100 (connected)

GENERAL.DEVICE:piabazzite
GENERAL.TYPE:wireguard
GENERAL.STATE:100 (connected)

GENERAL.DEVICE:lo
GENERAL.TYPE:loopback
GENERAL.STATE:100 (connected)
"""
        self.assertTrue(network_manager.physical_network_available_from_nmcli(output))

    def test_virtual_only_devices_do_not_count_as_underlay(self) -> None:
        output = """GENERAL.DEVICE:piabazzite
GENERAL.TYPE:wireguard
GENERAL.STATE:100 (connected)
GENERAL.DEVICE:podman0
GENERAL.TYPE:bridge
GENERAL.STATE:100 (connected)
GENERAL.DEVICE:lo
GENERAL.TYPE:loopback
GENERAL.STATE:100 (connected)
"""
        self.assertFalse(network_manager.physical_network_available_from_nmcli(output))

    def test_connecting_wifi_is_not_yet_available(self) -> None:
        output = """GENERAL.DEVICE:wlo1
GENERAL.TYPE:wifi
GENERAL.STATE:70 (connecting)
"""
        self.assertFalse(network_manager.physical_network_available_from_nmcli(output))

    def test_connected_ethernet_counts_as_underlay(self) -> None:
        output = """GENERAL.DEVICE:enp4s0
GENERAL.TYPE:ethernet
GENERAL.STATE:100 (connected)
"""
        self.assertTrue(network_manager.physical_network_available_from_nmcli(output))

    def test_runtime_query_uses_numeric_general_device_state(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "GENERAL.DEVICE:wlo1\n"
                "GENERAL.TYPE:wifi\n"
                "GENERAL.STATE:100 (verbunden)\n"
            ),
            stderr="",
        )
        with patch.object(network_manager, "ensure_available"), patch.object(
            network_manager, "_run", return_value=completed
        ) as run:
            self.assertTrue(network_manager.physical_network_available())
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[:3], ["nmcli", "-t", "-f"])
        self.assertIn("GENERAL.STATE", arguments[3])
        self.assertEqual(arguments[-2:], ["device", "show"])


if __name__ == "__main__":
    unittest.main()
