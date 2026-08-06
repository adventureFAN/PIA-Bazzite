from __future__ import annotations

import socket
import unittest

from pia_bazzite.network_probes import (
    DNS_TEST_ADDRESS,
    IPV4_TEST_ADDRESS,
    IPV6_TEST_ADDRESS,
    NetworkProbeBaseline,
    NetworkProbeError,
)


class NetworkProbeBaselineTests(unittest.TestCase):
    def test_capture_requires_working_ipv4_baseline(self) -> None:
        def tcp_probe(family: int, address: str, port: int, timeout: float) -> bool:
            return False

        with self.assertRaises(NetworkProbeError):
            NetworkProbeBaseline.capture(
                tcp_probe=tcp_probe,
                dns_udp_probe=lambda address, timeout: False,
            )

    def test_capture_records_only_paths_that_work_before_firewall(self) -> None:
        calls: list[tuple[int, str, int]] = []

        def tcp_probe(family: int, address: str, port: int, timeout: float) -> bool:
            calls.append((family, address, port))
            return (family, address, port) in {
                (socket.AF_INET, IPV4_TEST_ADDRESS, 443),
                (socket.AF_INET, DNS_TEST_ADDRESS, 53),
            }

        baseline = NetworkProbeBaseline.capture(
            tcp_probe=tcp_probe,
            dns_udp_probe=lambda address, timeout: True,
        )

        self.assertTrue(baseline.ipv4_tcp)
        self.assertFalse(baseline.ipv6_tcp)
        self.assertTrue(baseline.dns_tcp)
        self.assertTrue(baseline.dns_udp)
        self.assertIn((socket.AF_INET6, IPV6_TEST_ADDRESS, 443), calls)

    def test_blocked_check_retests_every_available_baseline_path(self) -> None:
        baseline = NetworkProbeBaseline(
            ipv4_tcp=True,
            ipv6_tcp=True,
            dns_tcp=True,
            dns_udp=True,
        )
        calls: list[tuple[int, str, int]] = []

        def tcp_probe(family: int, address: str, port: int, timeout: float) -> bool:
            calls.append((family, address, port))
            return False

        self.assertTrue(
            baseline.ordinary_path_is_blocked(
                tcp_probe=tcp_probe,
                dns_udp_probe=lambda address, timeout: False,
            )
        )
        self.assertEqual(
            calls,
            [
                (socket.AF_INET, IPV4_TEST_ADDRESS, 443),
                (socket.AF_INET6, IPV6_TEST_ADDRESS, 443),
                (socket.AF_INET, DNS_TEST_ADDRESS, 53),
            ],
        )

    def test_any_reachable_baseline_path_refuses_unlock(self) -> None:
        baseline = NetworkProbeBaseline(
            ipv4_tcp=True,
            ipv6_tcp=False,
            dns_tcp=True,
            dns_udp=True,
        )

        def tcp_probe(family: int, address: str, port: int, timeout: float) -> bool:
            return port == 53

        self.assertFalse(
            baseline.ordinary_path_is_blocked(
                tcp_probe=tcp_probe,
                dns_udp_probe=lambda address, timeout: False,
            )
        )

    def test_unavailable_optional_paths_are_not_invented_later(self) -> None:
        baseline = NetworkProbeBaseline(
            ipv4_tcp=True,
            ipv6_tcp=False,
            dns_tcp=False,
            dns_udp=False,
        )
        calls: list[tuple[int, str, int]] = []

        def tcp_probe(family: int, address: str, port: int, timeout: float) -> bool:
            calls.append((family, address, port))
            return False

        self.assertTrue(
            baseline.ordinary_path_is_blocked(
                tcp_probe=tcp_probe,
                dns_udp_probe=lambda address, timeout: (_ for _ in ()).throw(
                    AssertionError("UDP DNS must not be probed without a baseline")
                ),
            )
        )
        self.assertEqual(calls, [(socket.AF_INET, IPV4_TEST_ADDRESS, 443)])


if __name__ == "__main__":
    unittest.main()
