from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import shutil
import subprocess
from typing import Protocol, Sequence


VPN_INTERFACE_NAME = "piabazzite"
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


class NetworkPathError(RuntimeError):
    """The physical path to the exact WireGuard endpoint is not trustworthy."""


@dataclass(frozen=True, slots=True)
class RouteResult:
    returncode: int
    stdout: str
    stderr: str


class RouteRunner(Protocol):
    def run(self, arguments: Sequence[str], *, timeout: float) -> RouteResult:
        ...


class SubprocessRouteRunner:
    def run(self, arguments: Sequence[str], *, timeout: float) -> RouteResult:
        try:
            completed = subprocess.run(
                list(arguments),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise NetworkPathError("The fixed /usr/sbin/ip route tool is unavailable.") from exc
        except subprocess.TimeoutExpired as exc:
            raise NetworkPathError("Physical interface discovery timed out.") from exc
        except OSError as exc:
            raise NetworkPathError(f"Physical interface discovery failed: {exc}") from exc
        return RouteResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def discover_physical_interface(
    endpoint: str,
    *,
    runner: RouteRunner | None = None,
    timeout: float = 10.0,
) -> str:
    """Return the exact non-VPN interface currently routing to one endpoint.

    This must run before the WireGuard profile starts. The endpoint is numeric,
    so discovery requires no DNS request between firewall preparation and VPN
    startup.
    """

    host, family = _endpoint_host(endpoint)
    if timeout <= 0 or timeout > 30:
        raise ValueError("Route discovery timeout must be greater than 0 and at most 30 seconds.")

    command = _ip_command() if runner is None else "ip"
    route_runner = runner if runner is not None else SubprocessRouteRunner()
    result = route_runner.run(
        [command, f"-{family}", "route", "get", host],
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown route error").strip()
        raise NetworkPathError(f"No usable route to the WireGuard endpoint: {detail}")

    interface = _extract_route_interface(result.stdout)
    if interface in {"lo", VPN_INTERFACE_NAME}:
        raise NetworkPathError(
            f"Endpoint route uses forbidden interface {interface!r}; disconnect the existing VPN first."
        )
    return interface


def _ip_command() -> str:
    for candidate in ("/usr/sbin/ip", "/usr/bin/ip"):
        if shutil.which(candidate) == candidate:
            return candidate
    discovered = shutil.which("ip")
    if discovered:
        return discovered
    raise NetworkPathError("The ip route tool is unavailable.")


def _endpoint_host(endpoint: str) -> tuple[str, int]:
    if not isinstance(endpoint, str) or endpoint != endpoint.strip() or not endpoint:
        raise NetworkPathError("Endpoint must be a non-empty trimmed string.")
    if endpoint.startswith("["):
        close = endpoint.find("]")
        if close <= 1 or close + 1 >= len(endpoint) or endpoint[close + 1] != ":":
            raise NetworkPathError("IPv6 endpoint must use [address]:port syntax.")
        host = endpoint[1:close]
        port_text = endpoint[close + 2 :]
    else:
        if endpoint.count(":") != 1:
            raise NetworkPathError("IPv4 endpoint must use address:port syntax.")
        host, port_text = endpoint.rsplit(":", 1)
    if not port_text.isascii() or not port_text.isdecimal():
        raise NetworkPathError("Endpoint port must be decimal.")
    port = int(port_text, 10)
    if not 1 <= port <= 65535:
        raise NetworkPathError("Endpoint port is outside the valid range.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise NetworkPathError("Endpoint address must be numeric IPv4 or IPv6.") from exc
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local:
        raise NetworkPathError("Endpoint uses an unsafe special-purpose address.")
    return address.compressed, address.version


def _extract_route_interface(output: str) -> str:
    tokens = output.replace("\n", " ").split()
    interfaces = [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == "dev"]
    normalized = {
        interface
        for interface in interfaces
        if _INTERFACE_PATTERN.fullmatch(interface)
    }
    if len(normalized) != 1:
        raise NetworkPathError("Route output did not contain exactly one safe interface.")
    return next(iter(normalized))


__all__ = [
    "NetworkPathError",
    "RouteResult",
    "RouteRunner",
    "SubprocessRouteRunner",
    "discover_physical_interface",
]
