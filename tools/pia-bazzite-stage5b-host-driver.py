#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pia_bazzite import network_manager
from pia_bazzite.credentials import CredentialStore
from pia_bazzite.kill_switch_client import KillSwitchStatus
from pia_bazzite.kill_switch_connection import (
    ConnectionEvent,
    ConnectionPlan,
    IntentionalDisconnectError,
    KillSwitchConnectionOrchestrator,
    PostConnectVerificationError,
    VpnStartError,
    read_wireguard_endpoint,
)
from pia_bazzite.kill_switch_session import KillSwitchSessionClient
from pia_bazzite.logging_utils import mask_ip_address
from pia_bazzite.models import Region
from pia_bazzite.network_paths import discover_physical_interface
from pia_bazzite.pia_api import create_wireguard_config, fetch_public_network_info
from pia_bazzite.region_cache import load_regions
from pia_bazzite.settings import cache_dir, create_settings


EXIT_SAFE_FAILURE = 20
EXIT_FIREWALL_RETAINED = 21
FASTEST_ID = "__fastest__"
IPV4_TEST_ADDRESS = "1.1.1.1"
IPV6_TEST_ADDRESS = "2606:4700:4700::1111"


class HostTestError(RuntimeError):
    pass


def _probe_tcp(family: int, address: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((address, port))
        return True
    except OSError:
        return False


def _probe_dns_udp(address: str, timeout: float = 5.0) -> bool:
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
    return source[0] == address and source[1] == 53 and len(response) >= 12 and response[:2] == query[:2]


def _select_region(regions: Iterable[Region], requested_id: str, settings) -> Region:
    available = list(regions)
    if not available:
        raise HostTestError(
            "No cached PIA regions are available. Start PIA Bazzite once and reload the server list."
        )

    by_id = {region.region_id: region for region in available}
    candidates = [
        requested_id.strip(),
        str(settings.value("connection/selected_region_id", "")).strip(),
        str(settings.value("connection/active_region_id", "")).strip(),
    ]
    for candidate in candidates:
        if candidate and candidate != FASTEST_ID and candidate in by_id:
            return by_id[candidate]

    measured = [region for region in available if region.ping_ms is not None]
    if measured:
        return min(measured, key=lambda region: float(region.ping_ms or 0.0))
    return sorted(available, key=lambda region: (region.geo, region.name.casefold()))[0]


def _require_initial_disabled(status: KillSwitchStatus) -> None:
    if status.state != "disabled" or status.present or not status.verified or status.problems:
        raise HostTestError(
            "A previous production kill-switch table already exists. Use the Stage-5B emergency reset before retrying."
        )


def _event_sink(event: ConnectionEvent) -> None:
    label = "PASS" if event.level == "ok" else "INFO"
    if event.level in {"warning", "error"}:
        label = event.level.upper()
    print(f"{label:<7} {event.message}", flush=True)


def _safe_disconnect_without_unlock(profile_uuid: str) -> None:
    try:
        network_manager.disconnect(profile_uuid)
    except Exception as exc:
        print(f"WARNING VPN rollback failed while the firewall remained active: {exc}")
        return
    try:
        connected = network_manager.is_connected()
    except Exception as exc:
        print(f"WARNING VPN rollback could not be verified: {exc}")
        return
    if connected:
        print("WARNING NetworkManager still reports the VPN as connected; firewall remains active.")
    else:
        print("PASS    Unverified VPN was disconnected while the firewall remained active.")


def run(region_id: str) -> int:
    settings = create_settings()
    credentials = CredentialStore(settings).load()
    if credentials is None:
        raise HostTestError(
            "No saved PIA credentials were found. Open PIA Bazzite once and save the account first."
        )

    if network_manager.is_connected():
        raise HostTestError(
            "PIA Bazzite is already connected. Disconnect it and close the normal app before this host test."
        )

    region = _select_region(load_regions(), region_id, settings)
    print(f"INFO    Test region: {region.name} ({region.region_id})")

    if not _probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443):
        raise HostTestError("Baseline IPv4 internet access is unavailable before the test.")
    print("PASS    Baseline IPv4 TCP connectivity works.")

    ipv6_available = _probe_tcp(socket.AF_INET6, IPV6_TEST_ADDRESS, 443)
    print(
        "PASS    Baseline IPv6 TCP connectivity works."
        if ipv6_available
        else "SKIP    No working baseline IPv6 route is available."
    )
    dns_tcp_available = _probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 53)
    print(
        "PASS    Baseline direct DNS-over-TCP connectivity works."
        if dns_tcp_available
        else "SKIP    Direct DNS-over-TCP baseline is unavailable."
    )
    dns_udp_available = _probe_dns_udp(IPV4_TEST_ADDRESS)
    print(
        "PASS    Baseline direct DNS-over-UDP connectivity works."
        if dns_udp_available
        else "SKIP    Direct DNS-over-UDP baseline is unavailable."
    )

    baseline_info = fetch_public_network_info(timeout=12.0)
    print(f"PASS    Baseline public IP detected: {mask_ip_address(baseline_info.ip_address)}")

    config_path = cache_dir() / f"{network_manager.INTERFACE_NAME}.conf"
    session = KillSwitchSessionClient(timeout=120.0)
    firewall_may_be_active = False
    profile_uuid = ""

    try:
        create_wireguard_config(
            config_path=config_path,
            credentials=credentials,
            region=region,
        )
        endpoint = read_wireguard_endpoint(config_path)
        interface = discover_physical_interface(endpoint)
        print(f"PASS    Private WireGuard config created for one numeric endpoint.")
        print(f"PASS    Endpoint escape route uses physical interface {interface}.")

        print("INFO    A Polkit password dialog may appear now.")
        session.open()
        initial_status = session.status()
        if initial_status.present:
            firewall_may_be_active = True
        _require_initial_disabled(initial_status)
        print("PASS    No previous production kill-switch table is active.")

        plan = ConnectionPlan.create(
            config_path=config_path,
            physical_interfaces=(interface,),
            endpoints=(endpoint,),
        )
        orchestrator = KillSwitchConnectionOrchestrator(
            session=session,
            vpn_backend=network_manager,
            event_sink=_event_sink,
        )

        # From this point onward, every uncertain failure is treated as though
        # the firewall may be active. The external safety-reset timer remains
        # armed unless the complete test returns success.
        firewall_may_be_active = True
        result = orchestrator.connect(
            plan,
            kill_switch_enabled=True,
            vpn_connected_before=False,
        )
        profile_uuid = result.profile_uuid

        if not _probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443):
            _safe_disconnect_without_unlock(profile_uuid)
            raise HostTestError(
                "IPv4 internet traffic did not work through the connected VPN; firewall retained."
            )
        vpn_info = fetch_public_network_info(timeout=12.0)
        print(f"PASS    VPN public IP detected: {mask_ip_address(vpn_info.ip_address)}")
        if vpn_info.ip_address == baseline_info.ip_address:
            _safe_disconnect_without_unlock(profile_uuid)
            raise HostTestError(
                "The public IP did not change after VPN connection; firewall retained."
            )
        print("PASS    Public IP changed after the verified VPN connection.")

        def blocked_path_probe() -> bool:
            checks: list[tuple[str, bool]] = []
            checks.append(
                (
                    "ordinary IPv4 TCP fallback is blocked",
                    not _probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443, 4.0),
                )
            )
            if ipv6_available:
                checks.append(
                    (
                        "ordinary IPv6 TCP fallback is blocked",
                        not _probe_tcp(socket.AF_INET6, IPV6_TEST_ADDRESS, 443, 4.0),
                    )
                )
            if dns_tcp_available:
                checks.append(
                    (
                        "direct DNS-over-TCP fallback is blocked",
                        not _probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 53, 4.0),
                    )
                )
            if dns_udp_available:
                checks.append(
                    (
                        "direct DNS-over-UDP fallback is blocked",
                        not _probe_dns_udp(IPV4_TEST_ADDRESS, 4.0),
                    )
                )
            for description, passed in checks:
                print(f"{'PASS' if passed else 'FAIL':<7} {description}")
            return bool(checks) and all(passed for _, passed in checks)

        disconnect_result = orchestrator.disconnect_intentionally(
            profile_uuid=profile_uuid,
            kill_switch_enabled=True,
            blocked_path_probe=blocked_path_probe,
        )
        disabled = disconnect_result.firewall_status
        if disabled is None or disabled.state != "disabled" or disabled.present:
            raise HostTestError("The helper did not return a verified disabled state.")
        firewall_may_be_active = False

        if not _probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443):
            raise HostTestError("Normal IPv4 internet access did not return after deliberate unlock.")
        restored_info = fetch_public_network_info(timeout=12.0)
        print(f"PASS    Normal public IP restored: {mask_ip_address(restored_info.ip_address)}")
        print("\nALL STAGE-5B REAL HOST CONNECTION TESTS PASSED")
        return 0

    except KeyboardInterrupt:
        print("\nERROR   Test interrupted by the user.")
        return EXIT_FIREWALL_RETAINED if firewall_may_be_active else EXIT_SAFE_FAILURE
    except IntentionalDisconnectError as exc:
        print(f"ERROR   {exc}")
        return EXIT_FIREWALL_RETAINED if exc.firewall_retained else EXIT_SAFE_FAILURE
    except (VpnStartError, PostConnectVerificationError) as exc:
        print(f"ERROR   {exc}")
        return EXIT_FIREWALL_RETAINED if exc.firewall_retained else EXIT_SAFE_FAILURE
    except Exception as exc:
        print(f"ERROR   {exc}")
        return EXIT_FIREWALL_RETAINED if firewall_may_be_active else EXIT_SAFE_FAILURE
    finally:
        try:
            session.close()
        except Exception as exc:
            print(f"WARNING Could not close the helper session cleanly: {exc}")
        try:
            config_path.unlink(missing_ok=True)
        except OSError as exc:
            print(f"WARNING Could not remove the temporary WireGuard config: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real Stage-5B PIA Bazzite host connect/disconnect safety test."
    )
    parser.add_argument(
        "--region-id",
        default="",
        help="Optional exact cached PIA region ID.",
    )
    args = parser.parse_args()
    try:
        return run(args.region_id)
    except Exception as exc:
        print(f"ERROR   {exc}")
        return EXIT_SAFE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
