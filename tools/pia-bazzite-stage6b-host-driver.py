#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Iterable
import uuid


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
from pia_bazzite.kill_switch_recovery import (
    FirewallRoutePlan,
    KillSwitchRecoveryOrchestrator,
    PreparedServerSwitch,
    ProtectedReconnectError,
    ProtectedServerSwitchError,
    RecoveryEvent,
)
from pia_bazzite.kill_switch_session import KillSwitchSessionClient
from pia_bazzite.logging_utils import mask_ip_address
from pia_bazzite.models import Region
from pia_bazzite.network_paths import discover_physical_interface
from pia_bazzite.network_probes import (
    DNS_TEST_ADDRESS,
    IPV4_TEST_ADDRESS,
    IPV6_TEST_ADDRESS,
    NetworkProbeBaseline,
    probe_dns_udp,
    probe_tcp,
)
from pia_bazzite.pia_api import create_wireguard_config, fetch_public_network_info
from pia_bazzite.region_cache import load_regions
from pia_bazzite.settings import cache_dir, create_settings


EXIT_SAFE_FAILURE = 20
EXIT_FIREWALL_RETAINED = 21
FASTEST_ID = "__fastest__"
SUDO_PATH = Path("/usr/bin/sudo")
SYSTEM_PYTHON = Path("/usr/bin/python3")
SENTINEL_PATH = ROOT / "tools" / "pia-bazzite-stage6b-leak-sentinel.py"


class HostRecoveryTestError(RuntimeError):
    pass


class LeakSentinel:
    def __init__(self, *, interface: str, baseline: NetworkProbeBaseline) -> None:
        token = uuid.uuid4().hex
        self.interface = interface
        self.baseline = baseline
        self.result_path = Path(f"/tmp/pia-bazzite-stage6b-sentinel-{token}.json")
        self.stop_path = Path(f"/tmp/pia-bazzite-stage6b-sentinel-stop-{token}")
        self.process: subprocess.Popen[str] | None = None
        self.direct_ipv6 = False
        self.direct_dns_tcp = False
        self.direct_dns_udp = False

    def _argv(self, *, baseline_only: bool = False) -> list[str]:
        argv = [
            str(SUDO_PATH),
            "-n",
            str(SYSTEM_PYTHON),
            str(SENTINEL_PATH),
            "--interface",
            self.interface,
            "--result",
            str(self.result_path),
            "--stop-file",
            str(self.stop_path),
        ]
        check_ipv6 = self.baseline.ipv6_tcp if baseline_only else self.direct_ipv6
        check_dns_tcp = self.baseline.dns_tcp if baseline_only else self.direct_dns_tcp
        check_dns_udp = self.baseline.dns_udp if baseline_only else self.direct_dns_udp
        if check_ipv6:
            argv.append("--check-ipv6")
        if check_dns_tcp:
            argv.append("--check-dns-tcp")
        if check_dns_udp:
            argv.append("--check-dns-udp")
        if baseline_only:
            argv.extend(["--baseline-only", "--max-seconds", "10"])
        return argv

    def prove_direct_baseline(self) -> None:
        self._clean_files()
        self._assert_no_stale_files("before the direct baseline")
        completed = subprocess.run(
            self._argv(baseline_only=True),
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        payload = self._read_result()
        if completed.returncode != 0 or not payload:
            detail = (completed.stderr or completed.stdout).strip()
            raise HostRecoveryTestError(
                "The physical-interface sentinel could not prove a direct IPv4 baseline. "
                + detail
            )
        successes = payload.get("successes", {})
        if not isinstance(successes, dict) or int(successes.get("ipv4_tcp", 0)) < 1:
            raise HostRecoveryTestError(
                "The physical-interface sentinel did not observe its required pre-lock IPv4 path."
            )
        self.direct_ipv6 = int(successes.get("ipv6_tcp", 0)) > 0
        self.direct_dns_tcp = int(successes.get("dns_tcp", 0)) > 0
        self.direct_dns_udp = int(successes.get("dns_udp", 0)) > 0
        monitored = ["IPv4 TCP"]
        if self.direct_ipv6:
            monitored.append("IPv6 TCP")
        if self.direct_dns_tcp:
            monitored.append("DNS/TCP")
        if self.direct_dns_udp:
            monitored.append("DNS/UDP")
        print(
            f"PASS    Direct physical-path baseline works on {self.interface}; "
            f"sentinel will monitor {', '.join(monitored)}."
        )
        self._clean_files()
        self._assert_no_stale_files("after the direct baseline")

    def start(self) -> None:
        self._clean_files()
        self._assert_no_stale_files("before the protected sentinel")
        self.process = subprocess.Popen(
            self._argv(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            payload = self._read_result()
            if payload and int(payload.get("iterations", 0)) >= 1:
                if bool(payload.get("leak_detected")):
                    successes = payload.get("successes", {})
                    self.stop_without_assertion()
                    raise HostRecoveryTestError(
                        "DIRECT FALLBACK DETECTED immediately after the firewall lock: "
                        + json.dumps(successes, sort_keys=True)
                    )
                print(
                    "PASS    Continuous physical-interface leak sentinel is active and blocked."
                )
                return
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=2)
                raise HostRecoveryTestError(
                    "The leak sentinel exited before its first protected sample: "
                    + (stderr or stdout).strip()
                )
            time.sleep(0.1)
        raise HostRecoveryTestError("The leak sentinel did not produce a protected sample in time.")

    def assert_running_and_clean(self, label: str) -> None:
        if self.process is None:
            raise HostRecoveryTestError("The leak sentinel is not running.")
        if self.process.poll() is not None:
            stdout, stderr = self.process.communicate(timeout=2)
            payload = self._read_result()
            raise HostRecoveryTestError(
                f"The leak sentinel stopped during {label}: "
                + (stderr or stdout or json.dumps(payload, sort_keys=True)).strip()
            )
        payload = self._read_result()
        if not payload or int(payload.get("iterations", 0)) < 1:
            raise HostRecoveryTestError(f"The leak sentinel has no usable result during {label}.")
        if bool(payload.get("leak_detected")):
            raise HostRecoveryTestError(
                f"DIRECT FALLBACK DETECTED during {label}: "
                + json.dumps(payload.get("successes", {}), sort_keys=True)
            )
        print(
            f"PASS    Leak sentinel remains clean through {label} "
            f"({int(payload.get('iterations', 0))} samples)."
        )

    def stop_and_assert_clean(self) -> None:
        if self.process is None:
            return
        self.stop_path.touch(mode=0o600, exist_ok=True)
        try:
            stdout, stderr = self.process.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            stdout, stderr = self.process.communicate(timeout=5)
            raise HostRecoveryTestError("The leak sentinel did not stop cleanly.")
        payload = self._read_result()
        returncode = self.process.returncode
        self.process = None
        if not payload:
            raise HostRecoveryTestError(
                "The leak sentinel returned no final result: " + (stderr or stdout).strip()
            )
        if bool(payload.get("leak_detected")) or returncode not in {0}:
            raise HostRecoveryTestError(
                "DIRECT FALLBACK DETECTED by the transition sentinel: "
                + json.dumps(payload, sort_keys=True)
            )
        print(
            "PASS    Continuous physical-interface sentinel observed no direct fallback "
            f"across {int(payload.get('iterations', 0))} samples."
        )
        self._clean_files()

    def stop_without_assertion(self) -> None:
        if self.process is not None:
            try:
                self.stop_path.touch(mode=0o600, exist_ok=True)
                self.process.communicate(timeout=8)
            except Exception:
                try:
                    self.process.terminate()
                except Exception:
                    pass
            self.process = None
        self._clean_files()

    def _read_result(self) -> dict[str, object]:
        try:
            payload = json.loads(self.result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _sentinel_paths(self) -> tuple[Path, Path, Path]:
        return (
            self.result_path,
            self.stop_path,
            self.result_path.with_name(self.result_path.name + ".tmp"),
        )

    def _assert_no_stale_files(self, label: str) -> None:
        leftovers = [str(path) for path in self._sentinel_paths() if path.exists()]
        if leftovers:
            raise HostRecoveryTestError(
                f"Stale sentinel state remains {label}; refusing to read an old sample: "
                + ", ".join(leftovers)
            )

    def _clean_files(self) -> None:
        for path in self._sentinel_paths():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _select_initial_region(
    regions: Iterable[Region],
    requested_id: str,
    settings,
) -> Region:
    available = list(regions)
    if not available:
        raise HostRecoveryTestError(
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


def _select_switch_region(
    regions: Iterable[Region],
    *,
    initial: Region,
    requested_id: str,
) -> Region:
    available = [
        region
        for region in regions
        if region.region_id != initial.region_id
        and region.wireguard_ip != initial.wireguard_ip
    ]
    if requested_id.strip():
        for region in available:
            if region.region_id == requested_id.strip():
                return region
        raise HostRecoveryTestError(
            "The requested switch region is unavailable or uses the same WireGuard endpoint as the initial region."
        )
    if not available:
        raise HostRecoveryTestError(
            "A second cached PIA region with a different WireGuard endpoint is required."
        )
    measured = [region for region in available if region.ping_ms is not None]
    if measured:
        return min(measured, key=lambda region: float(region.ping_ms or 0.0))
    return sorted(available, key=lambda region: (region.geo, region.name.casefold()))[0]


def _require_initial_disabled(status: KillSwitchStatus) -> None:
    if status.state != "disabled" or status.present or not status.verified or status.problems:
        raise HostRecoveryTestError(
            "A previous production kill-switch table already exists. Use the Stage-6B emergency reset before retrying."
        )


def _event_sink(event: ConnectionEvent | RecoveryEvent) -> None:
    label = "PASS" if event.level == "ok" else "INFO"
    if event.level in {"warning", "error"}:
        label = event.level.upper()
    print(f"{label:<7} {event.message}", flush=True)


def _blocked_probe(baseline: NetworkProbeBaseline, *, label: str) -> bool:
    checks: list[tuple[str, bool]] = [
        (
            f"{label}: ordinary IPv4 TCP fallback is blocked",
            not probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443, 3.0),
        )
    ]
    if baseline.ipv6_tcp:
        checks.append(
            (
                f"{label}: ordinary IPv6 TCP fallback is blocked",
                not probe_tcp(socket.AF_INET6, IPV6_TEST_ADDRESS, 443, 3.0),
            )
        )
    if baseline.dns_tcp:
        checks.append(
            (
                f"{label}: direct DNS-over-TCP fallback is blocked",
                not probe_tcp(socket.AF_INET, DNS_TEST_ADDRESS, 53, 3.0),
            )
        )
    if baseline.dns_udp:
        checks.append(
            (
                f"{label}: direct DNS-over-UDP fallback is blocked",
                not probe_dns_udp(DNS_TEST_ADDRESS, 3.0),
            )
        )
    for description, passed in checks:
        print(f"{'PASS' if passed else 'FAIL':<7} {description}")
    return all(passed for _, passed in checks)


def _verify_vpn_internet(*, baseline_ip: str, label: str) -> str:
    if not probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443, 5.0):
        raise HostRecoveryTestError(f"IPv4 internet traffic did not work after {label}.")
    info = fetch_public_network_info(timeout=12.0)
    print(f"PASS    {label} public IP detected: {mask_ip_address(info.ip_address)}")
    if info.ip_address == baseline_ip:
        raise HostRecoveryTestError(
            f"The public IP did not differ from the ordinary connection after {label}."
        )
    return info.ip_address


def _safe_disconnect_without_unlock(profile_uuid: str) -> None:
    try:
        network_manager.disconnect(profile_uuid)
    except Exception as exc:
        print(f"WARNING VPN rollback failed while the firewall remained active: {exc}")


def run(initial_region_id: str, switch_region_id: str) -> int:
    for required in (SUDO_PATH, SYSTEM_PYTHON, SENTINEL_PATH):
        if not required.is_file():
            raise HostRecoveryTestError(f"Required fixed test boundary is missing: {required}")

    settings = create_settings()
    credentials = CredentialStore(settings).load()
    if credentials is None:
        raise HostRecoveryTestError(
            "No saved PIA credentials were found. Open PIA Bazzite once and save the account first."
        )
    if network_manager.is_connected():
        raise HostRecoveryTestError(
            "PIA Bazzite is already connected. Disconnect it and close the normal app before this host test."
        )

    regions = load_regions()
    initial_region = _select_initial_region(regions, initial_region_id, settings)
    switch_region = _select_switch_region(
        regions,
        initial=initial_region,
        requested_id=switch_region_id,
    )
    print(f"INFO    Initial region: {initial_region.name} ({initial_region.region_id})")
    print(f"INFO    Switch region: {switch_region.name} ({switch_region.region_id})")

    baseline = NetworkProbeBaseline.capture(timeout=4.0)
    print("PASS    Ordinary IPv4 baseline is reachable.")
    print("PASS    Ordinary IPv6 baseline is reachable." if baseline.ipv6_tcp else "SKIP    No ordinary IPv6 baseline is available.")
    print("PASS    Direct DNS-over-TCP baseline is reachable." if baseline.dns_tcp else "SKIP    Direct DNS-over-TCP baseline is unavailable.")
    print("PASS    Direct DNS-over-UDP baseline is reachable." if baseline.dns_udp else "SKIP    Direct DNS-over-UDP baseline is unavailable.")
    baseline_info = fetch_public_network_info(timeout=12.0)
    print(f"PASS    Ordinary public IP detected: {mask_ip_address(baseline_info.ip_address)}")

    initial_config = cache_dir() / f"{network_manager.INTERFACE_NAME}.conf"
    session = KillSwitchSessionClient(timeout=300.0)
    sentinel: LeakSentinel | None = None
    firewall_may_be_active = False
    profile_uuid = ""

    with tempfile.TemporaryDirectory(prefix="pia-bazzite-stage6b-") as temporary:
        candidate_config = Path(temporary) / f"{network_manager.INTERFACE_NAME}.conf"
        try:
            create_wireguard_config(
                config_path=initial_config,
                credentials=credentials,
                region=initial_region,
            )
            initial_endpoint = read_wireguard_endpoint(initial_config)
            initial_interface = discover_physical_interface(initial_endpoint)
            initial_plan = ConnectionPlan.create(
                config_path=initial_config,
                physical_interfaces=(initial_interface,),
                endpoints=(initial_endpoint,),
            )
            initial_route = FirewallRoutePlan.from_connection_plan(initial_plan)
            print(f"PASS    Initial endpoint route uses physical interface {initial_interface}.")

            sentinel = LeakSentinel(interface=initial_interface, baseline=baseline)
            sentinel.prove_direct_baseline()

            print("INFO    A Polkit password dialog may appear now.")
            session.open()
            initial_status = session.status()
            if initial_status.present:
                firewall_may_be_active = True
            _require_initial_disabled(initial_status)
            print("PASS    No previous production kill-switch table is active.")

            connection = KillSwitchConnectionOrchestrator(
                session=session,
                vpn_backend=network_manager,
                event_sink=_event_sink,
            )
            recovery = KillSwitchRecoveryOrchestrator(
                session=session,
                vpn_backend=network_manager,
                event_sink=_event_sink,
            )

            firewall_may_be_active = True
            connected = connection.connect(
                initial_plan,
                kill_switch_enabled=True,
                vpn_connected_before=False,
            )
            profile_uuid = connected.profile_uuid
            initial_vpn_ip = _verify_vpn_internet(
                baseline_ip=baseline_info.ip_address,
                label="Initial protected VPN",
            )

            sentinel.start()

            print("\n--- Simulated external tunnel loss and protected reconnect ---")
            network_manager.disconnect(profile_uuid)
            if network_manager.is_connected():
                raise HostRecoveryTestError("NetworkManager still reports the VPN after the simulated loss.")
            status_after_loss = session.status()
            if not status_after_loss.protection_active:
                raise HostRecoveryTestError("The firewall lock was not retained after tunnel loss.")
            print("PASS    VPN tunnel is down while the verified firewall lock remains active.")
            if not _blocked_probe(baseline, label="Tunnel loss"):
                raise HostRecoveryTestError("The ordinary path was not blocked after tunnel loss.")
            sentinel.assert_running_and_clean("the tunnel-loss interval")

            reconnected = recovery.reconnect(
                profile_uuid=profile_uuid,
                route_plan=initial_route,
                blocked_path_probe=lambda: _blocked_probe(
                    baseline,
                    label="Reconnect preflight",
                ),
            )
            if reconnected.profile_uuid != profile_uuid:
                raise HostRecoveryTestError("Protected reconnect changed the NetworkManager profile UUID.")
            reconnect_ip = _verify_vpn_internet(
                baseline_ip=baseline_info.ip_address,
                label="Protected reconnect",
            )
            if reconnect_ip != initial_vpn_ip:
                print("INFO    Reconnect received a different PIA exit IP; this is allowed.")
            sentinel.assert_running_and_clean("the protected reconnect")

            print("\n--- Protected server switch ---")
            create_wireguard_config(
                config_path=candidate_config,
                credentials=credentials,
                region=switch_region,
            )
            candidate = PreparedServerSwitch.create(config_path=candidate_config)
            if candidate.endpoint == initial_endpoint:
                raise HostRecoveryTestError("The prepared switch endpoint unexpectedly matches the initial endpoint.")
            print("PASS    A distinct private candidate configuration was prepared through the old VPN.")

            switched = recovery.switch_server(
                current_profile_uuid=profile_uuid,
                current_route_plan=initial_route,
                candidate=candidate,
                blocked_path_probe=lambda: _blocked_probe(
                    baseline,
                    label="Server-switch offline interval",
                ),
                physical_interface_resolver=discover_physical_interface,
            )
            profile_uuid = switched.profile_uuid
            if switched.connection_plan.physical_interfaces != (initial_interface,):
                raise HostRecoveryTestError(
                    "The switch selected a different physical interface than the continuously monitored route; "
                    "this Stage-6B gate refuses to claim a complete sentinel result."
                )
            if switched.connection_plan.endpoints != (candidate.endpoint,):
                raise HostRecoveryTestError("The server switch did not retain the exact candidate endpoint.")
            switched_ip = _verify_vpn_internet(
                baseline_ip=baseline_info.ip_address,
                label="Protected server switch",
            )
            if switched_ip == initial_vpn_ip:
                print("WARNING The two PIA regions reported the same public exit IP; endpoint replacement was still verified.")
            else:
                print("PASS    Public exit IP changed across the protected server switch.")
            sentinel.assert_running_and_clean("the protected server switch")

            print("\n--- Final deliberate disconnect and unlock ---")
            def final_blocked_probe() -> bool:
                blocked = _blocked_probe(baseline, label="Final intentional disconnect")
                if blocked and sentinel is not None:
                    sentinel.stop_and_assert_clean()
                return blocked

            disconnected = connection.disconnect_intentionally(
                profile_uuid=profile_uuid,
                kill_switch_enabled=True,
                blocked_path_probe=final_blocked_probe,
            )
            disabled = disconnected.firewall_status
            if disabled is None or disabled.state != "disabled" or disabled.present:
                raise HostRecoveryTestError("The helper did not return a verified disabled state.")
            firewall_may_be_active = False

            if not probe_tcp(socket.AF_INET, IPV4_TEST_ADDRESS, 443, 5.0):
                raise HostRecoveryTestError("Normal IPv4 connectivity did not return after deliberate unlock.")
            restored = fetch_public_network_info(timeout=12.0)
            print(f"PASS    Normal public IP restored: {mask_ip_address(restored.ip_address)}")
            print("\nALL STAGE-6B REAL RECOVERY AND SERVER-SWITCH TESTS PASSED")
            return 0

        except KeyboardInterrupt:
            print("\nERROR   Test interrupted by the user.")
            return EXIT_FIREWALL_RETAINED if firewall_may_be_active else EXIT_SAFE_FAILURE
        except (ProtectedReconnectError, ProtectedServerSwitchError) as exc:
            print(f"ERROR   {exc}")
            if getattr(exc, "rollback_error", ""):
                print(f"WARNING VPN rollback detail: {exc.rollback_error}")
            return EXIT_FIREWALL_RETAINED
        except IntentionalDisconnectError as exc:
            print(f"ERROR   {exc}")
            return EXIT_FIREWALL_RETAINED if exc.firewall_retained else EXIT_SAFE_FAILURE
        except (VpnStartError, PostConnectVerificationError) as exc:
            print(f"ERROR   {exc}")
            return EXIT_FIREWALL_RETAINED if exc.firewall_retained else EXIT_SAFE_FAILURE
        except Exception as exc:
            print(f"ERROR   {exc}")
            if firewall_may_be_active and profile_uuid:
                _safe_disconnect_without_unlock(profile_uuid)
            return EXIT_FIREWALL_RETAINED if firewall_may_be_active else EXIT_SAFE_FAILURE
        finally:
            if sentinel is not None:
                sentinel.stop_without_assertion()
            try:
                session.close()
            except Exception as exc:
                print(f"WARNING Could not close the helper session cleanly: {exc}")
            for path in (initial_config, candidate_config):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    print(f"WARNING Could not remove temporary WireGuard config {path}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real Stage-6B fail-closed tunnel-loss, reconnect, and server-switch host test."
    )
    parser.add_argument("--initial-region-id", default="")
    parser.add_argument("--switch-region-id", default="")
    args = parser.parse_args()
    try:
        return run(args.initial_region_id, args.switch_region_id)
    except Exception as exc:
        print(f"ERROR   {exc}")
        return EXIT_SAFE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
