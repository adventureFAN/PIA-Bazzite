from __future__ import annotations

import unittest

from pia_bazzite.network_paths import (
    NetworkPathError,
    RouteResult,
    discover_physical_interface,
)


class FakeRunner:
    def __init__(self, result: RouteResult) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def run(self, arguments, *, timeout: float) -> RouteResult:
        self.calls.append((tuple(arguments), timeout))
        return self.result


class NetworkPathTests(unittest.TestCase):
    def test_ipv4_route_returns_one_physical_interface(self) -> None:
        runner = FakeRunner(
            RouteResult(
                0,
                "198.51.100.8 via 192.0.2.1 dev wlp4s0 src 192.0.2.20 uid 1000\n",
                "",
            )
        )
        interface = discover_physical_interface(
            "198.51.100.8:1337",
            runner=runner,
        )
        self.assertEqual(interface, "wlp4s0")
        self.assertEqual(
            runner.calls,
            [(('ip', '-4', 'route', 'get', '198.51.100.8'), 10.0)],
        )

    def test_ipv6_route_uses_numeric_host_without_brackets(self) -> None:
        runner = FakeRunner(
            RouteResult(
                0,
                "2001:db8::8 from :: via 2001:db8::1 dev enp5s0 src 2001:db8::20 metric 100\n",
                "",
            )
        )
        interface = discover_physical_interface(
            "[2001:db8::8]:1337",
            runner=runner,
        )
        self.assertEqual(interface, "enp5s0")
        self.assertEqual(runner.calls[0][0][1:4], ("-6", "route", "get"))

    def test_route_failure_is_rejected(self) -> None:
        runner = FakeRunner(RouteResult(2, "", "Network is unreachable"))
        with self.assertRaises(NetworkPathError):
            discover_physical_interface("198.51.100.8:1337", runner=runner)

    def test_vpn_loopback_and_ambiguous_routes_are_rejected(self) -> None:
        for output in (
            "198.51.100.8 dev piabazzite src 10.0.0.2\n",
            "127.0.0.1 dev lo src 127.0.0.1\n",
            "198.51.100.8 dev wlp4s0 dev enp5s0\n",
            "198.51.100.8 via 192.0.2.1 src 192.0.2.20\n",
        ):
            with self.subTest(output=output):
                runner = FakeRunner(RouteResult(0, output, ""))
                with self.assertRaises(NetworkPathError):
                    discover_physical_interface(
                        "198.51.100.8:1337",
                        runner=runner,
                    )

    def test_hostnames_and_special_addresses_are_rejected_before_route_call(self) -> None:
        for endpoint in (
            "vpn.example:1337",
            "127.0.0.1:1337",
            "[::1]:1337",
            "198.51.100.8:0",
            "198.51.100.8;reboot:1337",
        ):
            with self.subTest(endpoint=endpoint):
                runner = FakeRunner(RouteResult(0, "", ""))
                with self.assertRaises(NetworkPathError):
                    discover_physical_interface(endpoint, runner=runner)
                self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
