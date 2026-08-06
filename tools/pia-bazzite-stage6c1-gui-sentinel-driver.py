#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
HELPER_ROOT = ROOT / "helper"
for candidate in (str(ROOT), str(HELPER_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from pia_bazzite import __app_id__, network_manager
from pia_bazzite.logging_utils import mask_ip_address
from pia_bazzite.network_paths import discover_physical_interface
from pia_bazzite.network_probes import NetworkProbeBaseline
from pia_bazzite.pia_api import fetch_public_network_info
from pia_bazzite.single_instance import instance_is_running
from pia_bazzite_kill_switch_helper.core import TABLE_NAME, parse_status_json


EXIT_SAFE_FAILURE = 20
EXIT_FIREWALL_RETAINED = 21
SUDO_PATH = Path("/usr/bin/sudo")
SYSTEM_PYTHON = Path("/usr/bin/python3")
NFT_PATHS = (Path("/usr/sbin/nft"), Path("/usr/bin/nft"))
SENTINEL_PATH = ROOT / "tools" / "pia-bazzite-stage6b-leak-sentinel.py"
APP_PYTHON = ROOT / ".venv" / "bin" / "python"
APP_MAIN = ROOT / "main.py"
LIVE_LOG_PATH = Path.home() / "Downloads" / "pia-stage6c1-gui-sentinel-live-log.txt"


class GuiSentinelTestError(RuntimeError):
    pass


class FirewallExpectedFailure(GuiSentinelTestError):
    """A failure occurred after the production lock had been observed."""



class GuiLeakSentinel:
    """Independent SO_BINDTODEVICE sentinel for the real Stage-6C GUI test."""

    def __init__(self, *, interface: str, baseline: NetworkProbeBaseline) -> None:
        token = uuid.uuid4().hex
        self.interface = interface
        self.baseline = baseline
        self.result_path = Path(f"/tmp/pia-bazzite-stage6b-sentinel-{token}.json")
        self.stop_path = Path(f"/tmp/pia-bazzite-stage6b-sentinel-stop-{token}")
        self.process: subprocess.Popen[str] | None = None
        self.lock_observed = False
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
        else:
            argv.extend(["--max-seconds", "600"])
        return argv

    def prove_direct_baseline(self) -> None:
        self._clean_files()
        self._assert_no_stale_files("before the GUI sentinel baseline")
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
            raise GuiSentinelTestError(
                "The independent GUI sentinel could not prove its direct IPv4 baseline. "
                + detail
            )
        successes = payload.get("successes", {})
        if not isinstance(successes, dict) or int(successes.get("ipv4_tcp", 0)) < 1:
            raise GuiSentinelTestError(
                "The independent GUI sentinel did not observe the required pre-lock IPv4 path."
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
            f"PASS    Independent direct-path baseline works on {self.interface}; "
            f"GUI sentinel will monitor {', '.join(monitored)}.",
            flush=True,
        )
        self._clean_files()
        self._assert_no_stale_files("after the GUI sentinel baseline")

    def start(self) -> None:
        self.lock_observed = True
        self._clean_files()
        self._assert_no_stale_files("before the protected GUI sentinel")
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
                    raise GuiSentinelTestError(
                        "DIRECT FALLBACK DETECTED when the GUI firewall lock appeared: "
                        + json.dumps(successes, sort_keys=True)
                    )
                print(
                    "PASS    Independent physical-interface GUI sentinel is active and blocked.",
                    flush=True,
                )
                return
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=2)
                raise GuiSentinelTestError(
                    "The independent GUI sentinel exited before its first protected sample: "
                    + (stderr or stdout).strip()
                )
            time.sleep(0.1)
        raise GuiSentinelTestError(
            "The independent GUI sentinel did not produce a protected sample in time."
        )

    def assert_running_and_clean(self, label: str, *, announce: bool = False) -> None:
        if self.process is None:
            raise GuiSentinelTestError("The independent GUI sentinel is not running.")
        if self.process.poll() is not None:
            stdout, stderr = self.process.communicate(timeout=2)
            payload = self._read_result()
            raise GuiSentinelTestError(
                f"The independent GUI sentinel stopped during {label}: "
                + (stderr or stdout or json.dumps(payload, sort_keys=True)).strip()
            )
        payload = self._read_result()
        if not payload or int(payload.get("iterations", 0)) < 1:
            raise GuiSentinelTestError(
                f"The independent GUI sentinel has no usable result during {label}."
            )
        if bool(payload.get("leak_detected")):
            raise GuiSentinelTestError(
                f"DIRECT FALLBACK DETECTED during {label}: "
                + json.dumps(payload.get("successes", {}), sort_keys=True)
            )
        if announce:
            print(
                f"PASS    Independent GUI sentinel remains clean through {label} "
                f"({int(payload.get('iterations', 0))} samples).",
                flush=True,
            )

    def stop_and_assert_clean(self) -> int:
        if self.process is None:
            return 0
        self.stop_path.touch(mode=0o600, exist_ok=True)
        try:
            stdout, stderr = self.process.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            stdout, stderr = self.process.communicate(timeout=5)
            raise GuiSentinelTestError("The independent GUI sentinel did not stop cleanly.")
        payload = self._read_result()
        returncode = self.process.returncode
        self.process = None
        if not payload:
            raise GuiSentinelTestError(
                "The independent GUI sentinel returned no final result: "
                + (stderr or stdout).strip()
            )
        if bool(payload.get("leak_detected")) or returncode not in {0}:
            raise GuiSentinelTestError(
                "DIRECT FALLBACK DETECTED by the independent GUI sentinel: "
                + json.dumps(payload, sort_keys=True)
            )
        iterations = int(payload.get("iterations", 0))
        print(
            "PASS    Independent GUI sentinel observed no direct fallback "
            f"across {iterations} samples.",
            flush=True,
        )
        self._clean_files()
        return iterations

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

    def _paths(self) -> tuple[Path, Path, Path]:
        return (
            self.result_path,
            self.stop_path,
            self.result_path.with_name(self.result_path.name + ".tmp"),
        )

    def _assert_no_stale_files(self, label: str) -> None:
        leftovers = [str(path) for path in self._paths() if path.exists()]
        if leftovers:
            raise GuiSentinelTestError(
                f"Stale independent sentinel state remains {label}: "
                + ", ".join(leftovers)
            )

    def _clean_files(self) -> None:
        for path in self._paths():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _nft_path() -> Path:
    for candidate in NFT_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise GuiSentinelTestError("nft is missing from the approved system paths.")


def _verified_table_state(nft_path: Path) -> tuple[bool, bool, tuple[str, ...]]:
    completed = subprocess.run(
        [
            str(SUDO_PATH),
            "-n",
            str(nft_path),
            "-j",
            "list",
            "table",
            "inet",
            TABLE_NAME,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).casefold()
        if "no such file" in detail or "does not exist" in detail or "nicht vorhanden" in detail:
            return False, True, ()
        raise GuiSentinelTestError(
            "Independent nftables status check failed: "
            + (completed.stderr or completed.stdout).strip()
        )
    status = parse_status_json(completed.stdout)
    problems = tuple(str(value) for value in status.get("problems", []))
    return bool(status.get("present")), bool(status.get("verified")), problems


def _require_verified_lock(nft_path: Path, label: str) -> None:
    present, verified, problems = _verified_table_state(nft_path)
    if not present or not verified or problems:
        raise GuiSentinelTestError(
            f"The production firewall lock was absent or unverified during {label}: "
            + (", ".join(problems) if problems else "table absent")
        )


def _wait_for_initial_protection(
    *,
    app_process: subprocess.Popen[bytes],
    nft_path: Path,
    sentinel: GuiLeakSentinel,
    timeout: float = 240.0,
) -> str:
    print("\nACTION  In PIA Bazzite, enable the Kill Switch and connect to any server.", flush=True)
    print("ACTION  Wait for the green status 'Geschützt'. The test continues automatically.", flush=True)
    deadline = time.monotonic() + timeout
    sentinel_started = False
    connected_since: float | None = None
    profile_uuid = ""
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise GuiSentinelTestError("PIA Bazzite closed before the protected GUI connection was ready.")
        present, verified, problems = _verified_table_state(nft_path)
        if present and not verified:
            raise GuiSentinelTestError(
                "The GUI created an unverified production firewall table: "
                + ", ".join(problems)
            )
        if present and verified and not sentinel_started:
            sentinel.start()
            sentinel_started = True
        if sentinel_started:
            sentinel.assert_running_and_clean("the initial protected GUI connection")
        state = network_manager.connection_state()
        if present and verified and state.connected:
            if state.uuid != profile_uuid:
                profile_uuid = state.uuid
                connected_since = time.monotonic()
            elif connected_since is not None and time.monotonic() - connected_since >= 2.0:
                sentinel.assert_running_and_clean(
                    "the stable initial protected GUI connection",
                    announce=True,
                )
                print("PASS    The GUI reached a stable protected connection.", flush=True)
                return profile_uuid
        else:
            connected_since = None
            profile_uuid = ""
        time.sleep(0.1)
    raise GuiSentinelTestError("Timed out waiting for the initial protected GUI connection.")


def _force_and_wait_for_reconnect(
    *,
    profile_uuid: str,
    nft_path: Path,
    sentinel: GuiLeakSentinel,
    timeout: float = 120.0,
) -> str:
    print("\n--- Independent GUI tunnel-loss and automatic-reconnect test ---", flush=True)
    _require_verified_lock(nft_path, "the forced GUI tunnel loss")
    network_manager.disconnect(profile_uuid)
    print("PASS    External tunnel loss was forced through NetworkManager.", flush=True)
    deadline = time.monotonic() + timeout
    saw_disconnected = False
    reconnected_since: float | None = None
    while time.monotonic() < deadline:
        _require_verified_lock(nft_path, "the GUI automatic reconnect")
        sentinel.assert_running_and_clean("the GUI automatic reconnect")
        state = network_manager.connection_state()
        if not state.connected:
            saw_disconnected = True
            reconnected_since = None
        elif saw_disconnected:
            if state.uuid != profile_uuid:
                raise GuiSentinelTestError(
                    "The automatic GUI reconnect activated a different NetworkManager profile UUID."
                )
            if reconnected_since is None:
                reconnected_since = time.monotonic()
            elif time.monotonic() - reconnected_since >= 2.0:
                sentinel.assert_running_and_clean(
                    "the complete GUI tunnel-loss and automatic-reconnect transition",
                    announce=True,
                )
                print("PASS    The GUI automatically restored the same protected VPN profile.", flush=True)
                return state.uuid
        time.sleep(0.1)
    raise GuiSentinelTestError("Timed out waiting for the GUI automatic reconnect.")


def _wait_for_server_switch(
    *,
    old_profile_uuid: str,
    old_public_ip: str,
    app_process: subprocess.Popen[bytes],
    nft_path: Path,
    sentinel: GuiLeakSentinel,
    timeout: float = 240.0,
) -> tuple[str, str]:
    print("\nACTION  In PIA Bazzite, select a DIFFERENT server and confirm the switch.", flush=True)
    print("ACTION  Do not disconnect manually; the test watches the whole transition.", flush=True)
    deadline = time.monotonic() + timeout
    saw_disconnected = False
    connected_since: float | None = None
    new_uuid = ""
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise GuiSentinelTestError("PIA Bazzite closed during the protected server switch.")
        _require_verified_lock(nft_path, "the GUI protected server switch")
        sentinel.assert_running_and_clean("the GUI protected server switch")
        state = network_manager.connection_state()
        if not state.connected:
            saw_disconnected = True
            connected_since = None
        elif saw_disconnected and state.uuid != old_profile_uuid:
            if state.uuid != new_uuid:
                new_uuid = state.uuid
                connected_since = time.monotonic()
            elif connected_since is not None and time.monotonic() - connected_since >= 2.0:
                sentinel.assert_running_and_clean(
                    "the complete GUI protected server switch",
                    announce=True,
                )
                info = fetch_public_network_info(timeout=12.0)
                print(
                    "PASS    Protected GUI server-switch public IP detected: "
                    + mask_ip_address(info.ip_address),
                    flush=True,
                )
                if info.ip_address == old_public_ip:
                    raise GuiSentinelTestError(
                        "The public exit IP did not change after the confirmed GUI server switch."
                    )
                print("PASS    The GUI completed a protected switch to a new VPN profile.", flush=True)
                return new_uuid, info.ip_address
        time.sleep(0.1)
    raise GuiSentinelTestError("Timed out waiting for a distinct protected GUI server switch.")


def _wait_for_deliberate_disconnect(
    *,
    app_process: subprocess.Popen[bytes],
    nft_path: Path,
    test_started_wallclock: float,
    timeout: float = 240.0,
) -> None:
    print("\nACTION  Save the app Live Log exactly as:", flush=True)
    print(f"ACTION  {LIVE_LOG_PATH}", flush=True)
    print("ACTION  Then click the normal VPN disconnect button in PIA Bazzite.", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise GuiSentinelTestError(
                "PIA Bazzite closed before the deliberate disconnect and Live Log save completed."
            )
        state = network_manager.connection_state()
        present, verified, problems = _verified_table_state(nft_path)
        if present and not verified:
            raise GuiSentinelTestError(
                "The firewall table became unverified during the final deliberate disconnect: "
                + ", ".join(problems)
            )
        if not state.connected and not present:
            try:
                stat = LIVE_LOG_PATH.stat()
            except OSError:
                time.sleep(0.2)
                continue
            if stat.st_size <= 0 or stat.st_mtime < test_started_wallclock:
                time.sleep(0.2)
                continue
            baseline = NetworkProbeBaseline.capture(timeout=4.0)
            if not baseline.ipv4_tcp:
                raise GuiSentinelTestError(
                    "Normal IPv4 connectivity did not return after the deliberate GUI disconnect."
                )
            info = fetch_public_network_info(timeout=12.0)
            print(
                "PASS    Normal public network access returned after the deliberate GUI disconnect: "
                + mask_ip_address(info.ip_address),
                flush=True,
            )
            print(f"PASS    GUI Live Log was saved: {LIVE_LOG_PATH}", flush=True)
            return
        time.sleep(0.2)
    raise GuiSentinelTestError(
        "Timed out waiting for the deliberate GUI disconnect, absent firewall table, and saved Live Log."
    )


def run() -> int:
    for required in (SUDO_PATH, SYSTEM_PYTHON, SENTINEL_PATH, APP_PYTHON, APP_MAIN):
        if not required.is_file():
            raise GuiSentinelTestError(f"Required fixed Stage-6C.1 boundary is missing: {required}")
    if network_manager.is_connected():
        raise GuiSentinelTestError("PIA Bazzite must be disconnected before the GUI sentinel test.")
    if instance_is_running(__app_id__, timeout_ms=350):
        raise GuiSentinelTestError(
            "A PIA Bazzite instance is already running before the GUI sentinel test."
        )

    nft_path = _nft_path()
    present, verified, problems = _verified_table_state(nft_path)
    if present or not verified or problems:
        raise GuiSentinelTestError(
            "A previous production firewall lock exists before the GUI sentinel test."
        )

    test_started_wallclock = time.time()
    baseline = NetworkProbeBaseline.capture(timeout=4.0)
    ordinary_info = fetch_public_network_info(timeout=12.0)
    print("PASS    Ordinary IPv4 baseline is reachable.", flush=True)
    print(
        "PASS    Ordinary IPv6 baseline is reachable."
        if baseline.ipv6_tcp
        else "SKIP    No ordinary IPv6 baseline is available.",
        flush=True,
    )
    print(
        "PASS    Direct DNS-over-TCP baseline is reachable."
        if baseline.dns_tcp
        else "SKIP    Direct DNS-over-TCP baseline is unavailable.",
        flush=True,
    )
    print(
        "PASS    Direct DNS-over-UDP baseline is reachable."
        if baseline.dns_udp
        else "SKIP    Direct DNS-over-UDP baseline is unavailable.",
        flush=True,
    )
    print(
        "PASS    Ordinary public IP detected: " + mask_ip_address(ordinary_info.ip_address),
        flush=True,
    )

    interface = discover_physical_interface("1.1.1.1:443")
    sentinel = GuiLeakSentinel(interface=interface, baseline=baseline)
    sentinel.prove_direct_baseline()

    print("\n--- Launch real Stage-6C GUI under independent observation ---", flush=True)
    if instance_is_running(__app_id__, timeout_ms=350):
        raise GuiSentinelTestError(
            "A PIA Bazzite instance appeared before the test GUI launch."
        )
    app_process = subprocess.Popen(
        [str(APP_PYTHON), str(APP_MAIN)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_observed = False
    sentinel_stopped = False
    try:
        old_uuid = _wait_for_initial_protection(
            app_process=app_process,
            nft_path=nft_path,
            sentinel=sentinel,
        )
        lock_observed = True
        initial_vpn_info = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Initial protected GUI public IP detected: "
            + mask_ip_address(initial_vpn_info.ip_address),
            flush=True,
        )
        if initial_vpn_info.ip_address == ordinary_info.ip_address:
            raise GuiSentinelTestError(
                "The initial protected GUI connection did not change the public IP."
            )

        reconnected_uuid = _force_and_wait_for_reconnect(
            profile_uuid=old_uuid,
            nft_path=nft_path,
            sentinel=sentinel,
        )
        reconnected_info = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Reconnected protected GUI public IP detected: "
            + mask_ip_address(reconnected_info.ip_address),
            flush=True,
        )
        if reconnected_info.ip_address == ordinary_info.ip_address:
            raise GuiSentinelTestError(
                "The automatic GUI reconnect returned the ordinary public IP."
            )

        _new_uuid, _new_ip = _wait_for_server_switch(
            old_profile_uuid=reconnected_uuid,
            old_public_ip=reconnected_info.ip_address,
            app_process=app_process,
            nft_path=nft_path,
            sentinel=sentinel,
        )
        _require_verified_lock(nft_path, "the final protected GUI state")
        sentinel.stop_and_assert_clean()
        sentinel_stopped = True
        print(
            "PASS    The independent sentinel stopped only after reconnect and server switch were verified.",
            flush=True,
        )

        _wait_for_deliberate_disconnect(
            app_process=app_process,
            nft_path=nft_path,
            test_started_wallclock=test_started_wallclock,
        )
        print("\nALL STAGE-6C.1 REAL GUI SENTINEL TESTS PASSED", flush=True)
        return 0
    except Exception as exc:
        if not sentinel_stopped:
            sentinel.stop_without_assertion()
        present_now, _verified_now, _problems_now = _verified_table_state(nft_path)
        if present_now or lock_observed or sentinel.lock_observed:
            raise FirewallExpectedFailure(str(exc)) from exc
        raise


def main() -> int:
    try:
        return run()
    except Exception as exc:
        print(f"ERROR   {exc}", file=sys.stderr, flush=True)
        if isinstance(exc, FirewallExpectedFailure):
            return EXIT_FIREWALL_RETAINED
        try:
            nft_path = _nft_path()
            present, _verified, _problems = _verified_table_state(nft_path)
        except Exception:
            present = True
        return EXIT_FIREWALL_RETAINED if present else EXIT_SAFE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
