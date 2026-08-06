from __future__ import annotations

from dataclasses import dataclass
import socket
from typing import Callable


IPV4_TEST_ADDRESS = "1.1.1.1"
IPV6_TEST_ADDRESS = "2606:4700:4700::1111"
DNS_TEST_ADDRESS = IPV4_TEST_ADDRESS


class NetworkProbeError(RuntimeError):
    """A fixed reachability probe could not establish a safe baseline."""


def probe_tcp(
    family: int,
    address: str,
    port: int,
    timeout: float = 5.0,
) -> bool:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((address, port))
        return True
    except OSError:
        return False


def probe_dns_udp(address: str, timeout: float = 5.0) -> bool:
    # Fixed transaction ID and a minimal A query for example.com. The result is
    # used only as a reachability signal; no response content is trusted.
    query = bytes.fromhex(
        "504901000001000000000000"
        "076578616d706c6503636f6d00"
        "00010001"
    )
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(query, (address, 53))
            response, source = sock.recvfrom(4096)
    except OSError:
        return False
    return (
        source[0] == address
        and source[1] == 53
        and len(response) >= 12
        and response[:2] == query[:2]
    )


@dataclass(frozen=True, slots=True)
class NetworkProbeBaseline:
    """Paths that worked before the firewall was enabled.

    Intentional disconnect may release the firewall only after every path that
    was reachable in this baseline is proven blocked while the VPN is down.
    IPv4 HTTPS is mandatory so the GUI never treats a completely offline host
    as a successful kill-switch probe.
    """

    ipv4_tcp: bool
    ipv6_tcp: bool
    dns_tcp: bool
    dns_udp: bool

    @classmethod
    def capture(
        cls,
        *,
        tcp_probe: Callable[[int, str, int, float], bool] = probe_tcp,
        dns_udp_probe: Callable[[str, float], bool] = probe_dns_udp,
        timeout: float = 4.0,
    ) -> "NetworkProbeBaseline":
        ipv4_tcp = bool(
            tcp_probe(socket.AF_INET, IPV4_TEST_ADDRESS, 443, timeout)
        )
        if not ipv4_tcp:
            raise NetworkProbeError(
                "Baseline IPv4 internet access is unavailable before the protected connection."
            )
        return cls(
            ipv4_tcp=True,
            ipv6_tcp=bool(
                tcp_probe(socket.AF_INET6, IPV6_TEST_ADDRESS, 443, timeout)
            ),
            dns_tcp=bool(
                tcp_probe(socket.AF_INET, DNS_TEST_ADDRESS, 53, timeout)
            ),
            dns_udp=bool(dns_udp_probe(DNS_TEST_ADDRESS, timeout)),
        )

    def ordinary_path_is_blocked(
        self,
        *,
        tcp_probe: Callable[[int, str, int, float], bool] = probe_tcp,
        dns_udp_probe: Callable[[str, float], bool] = probe_dns_udp,
        timeout: float = 4.0,
    ) -> bool:
        checks = [
            not tcp_probe(socket.AF_INET, IPV4_TEST_ADDRESS, 443, timeout)
        ]
        if self.ipv6_tcp:
            checks.append(
                not tcp_probe(socket.AF_INET6, IPV6_TEST_ADDRESS, 443, timeout)
            )
        if self.dns_tcp:
            checks.append(
                not tcp_probe(socket.AF_INET, DNS_TEST_ADDRESS, 53, timeout)
            )
        if self.dns_udp:
            checks.append(not dns_udp_probe(DNS_TEST_ADDRESS, timeout))
        return all(checks)


__all__ = [
    "DNS_TEST_ADDRESS",
    "IPV4_TEST_ADDRESS",
    "IPV6_TEST_ADDRESS",
    "NetworkProbeBaseline",
    "NetworkProbeError",
    "probe_dns_udp",
    "probe_tcp",
]
