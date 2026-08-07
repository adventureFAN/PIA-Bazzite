#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
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
from pia_bazzite.kill_switch_client import KillSwitchStatus
from pia_bazzite.kill_switch_crash_state import (
    CrashRecoveryDisposition,
    CrashRecoveryRecord,
    CrashRecoveryStore,
    CrashRecoveryVerifier,
)
from pia_bazzite.logging_utils import mask_ip_address
from pia_bazzite.network_paths import discover_physical_interface
from pia_bazzite.network_probes import (
    IPV4_TEST_ADDRESS,
    NetworkProbeBaseline,
)
from pia_bazzite.pia_api import fetch_public_network_info
from pia_bazzite.settings import crash_recovery_path
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


class CrashHostTestError(RuntimeError):
    pass


class CrashLeakSentinel:
    """Independent SO_BINDTODEVICE sentinel spanning the GUI SIGKILL."""

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
        else:
            argv.extend(["--max-seconds", "600"])
        return argv

    def prove_direct_baseline(self) -> None:
        self._clean_files()
        self._assert_no_stale_files("before the Stage-7B direct baseline")
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
            raise CrashHostTestError(
                "The crash-test sentinel could not prove its direct IPv4 baseline. "
                + detail
            )
        successes = payload.get("successes", {})
        if not isinstance(successes, dict) or int(successes.get("ipv4_tcp", 0)) < 1:
            raise CrashHostTestError(
                "The crash-test sentinel did not observe the mandatory pre-lock IPv4 path."
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
            f"crash sentinel will monitor {', '.join(monitored)}.",
            flush=True,
        )
        self._clean_files()
        self._assert_no_stale_files("after the Stage-7B direct baseline")

    def start(self) -> None:
        self._clean_files()
        self._assert_no_stale_files("before the protected Stage-7B sentinel")
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
                    raise CrashHostTestError(
                        "DIRECT FALLBACK DETECTED when the Stage-7B firewall lock appeared: "
                        + json.dumps(successes, sort_keys=True)
                    )
                print(
                    "PASS    Independent crash sentinel is active and the direct path is blocked.",
                    flush=True,
                )
                return
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=2)
                raise CrashHostTestError(
                    "The crash sentinel exited before its first protected sample: "
                    + (stderr or stdout).strip()
                )
            time.sleep(0.1)
        raise CrashHostTestError(
            "The crash sentinel did not produce a protected sample in time."
        )

    def assert_running_and_clean(self, label: str, *, announce: bool = False) -> int:
        if self.process is None:
            raise CrashHostTestError("The crash sentinel is not running.")
        if self.process.poll() is not None:
            stdout, stderr = self.process.communicate(timeout=2)
            payload = self._read_result()
            raise CrashHostTestError(
                f"The crash sentinel stopped during {label}: "
                + (stderr or stdout or json.dumps(payload, sort_keys=True)).strip()
            )
        payload = self._read_result()
        if not payload or int(payload.get("iterations", 0)) < 1:
            raise CrashHostTestError(
                f"The crash sentinel has no usable result during {label}."
            )
        if bool(payload.get("leak_detected")):
            raise CrashHostTestError(
                f"DIRECT FALLBACK DETECTED during {label}: "
                + json.dumps(payload.get("successes", {}), sort_keys=True)
            )
        iterations = int(payload.get("iterations", 0))
        if announce:
            print(
                f"PASS    Independent crash sentinel remains clean through {label} "
                f"({iterations} samples).",
                flush=True,
            )
        return iterations

    def stop_and_assert_clean(self) -> int:
        if self.process is None:
            return 0
        self.stop_path.touch(mode=0o600, exist_ok=True)
        try:
            stdout, stderr = self.process.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            stdout, stderr = self.process.communicate(timeout=5)
            raise CrashHostTestError("The crash sentinel did not stop cleanly.")
        payload = self._read_result()
        returncode = self.process.returncode
        self.process = None
        if not payload:
            raise CrashHostTestError(
                "The crash sentinel returned no final result: "
                + (stderr or stdout).strip()
            )
        if bool(payload.get("leak_detected")) or returncode != 0:
            raise CrashHostTestError(
                "DIRECT FALLBACK DETECTED by the final crash sentinel result: "
                + json.dumps(payload.get("successes", {}), sort_keys=True)
            )
        iterations = int(payload.get("iterations", 0))
        print(
            "PASS    Independent crash sentinel observed no direct fallback across "
            f"{iterations} samples.",
            flush=True,
        )
        self._clean_files()
        return iterations

    def stop_without_assertion(self) -> None:
        process = self.process
        if process is not None:
            try:
                self.stop_path.touch(mode=0o600, exist_ok=True)
            except OSError:
                pass
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=2)
            self.process = None
        self._clean_files()

    def _read_result(self) -> dict[str, object]:
        try:
            raw = self.result_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _clean_files(self) -> None:
        for path in (self.result_path, self.stop_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            self.result_path.with_name(self.result_path.name + ".tmp").unlink(
                missing_ok=True
            )
        except OSError:
            pass

    def _assert_no_stale_files(self, label: str) -> None:
        stale = [
            path
            for path in (
                self.result_path,
                self.stop_path,
                self.result_path.with_name(self.result_path.name + ".tmp"),
            )
            if path.exists() or path.is_symlink()
        ]
        if stale:
            raise CrashHostTestError(
                f"Unsafe stale sentinel files remain {label}: "
                + ", ".join(str(path) for path in stale)
            )


def _nft_path() -> Path:
    for candidate in NFT_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise CrashHostTestError("nft is missing from the approved system paths.")


def _read_table_status(nft_path: Path) -> dict[str, object]:
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
        if (
            "no such file" in detail
            or "does not exist" in detail
            or "nicht vorhanden" in detail
        ):
            return {
                "present": False,
                "verified": True,
                "state": "disabled",
                "problems": [],
                "physical_interfaces": [],
                "endpoints": [],
                "capabilities": ["inspect-route"],
                "table_generation": 1,
                "table": TABLE_NAME,
            }
        raise CrashHostTestError(
            "Independent nftables status check failed: "
            + (completed.stderr or completed.stdout).strip()
        )
    status = parse_status_json(completed.stdout)
    if not isinstance(status, dict):
        raise CrashHostTestError("The independent nftables parser returned no status object.")
    return status


def _kill_switch_status(document: dict[str, object]) -> KillSwitchStatus:
    problems_raw = document.get("problems", [])
    interfaces_raw = document.get("physical_interfaces", [])
    endpoints_raw = document.get("endpoints", [])
    capabilities_raw = document.get("capabilities", [])
    return KillSwitchStatus(
        action="status",
        state=str(document.get("state", "error")),
        present=bool(document.get("present")),
        verified=bool(document.get("verified")),
        table=str(document.get("table", TABLE_NAME)),
        table_generation=int(document.get("table_generation", 1)),
        capabilities=tuple(str(value) for value in capabilities_raw),
        problems=tuple(str(value) for value in problems_raw),
        payload=dict(document),
        physical_interfaces=tuple(str(value) for value in interfaces_raw),
        endpoints=tuple(str(value) for value in endpoints_raw),
    )


def _require_verified_lock(nft_path: Path, label: str) -> KillSwitchStatus:
    status = _kill_switch_status(_read_table_status(nft_path))
    if not status.protection_active:
        detail = ", ".join(status.problems) if status.problems else "table absent"
        raise CrashHostTestError(
            f"The production firewall lock was absent or unverified during {label}: {detail}"
        )
    return status


def _load_record() -> CrashRecoveryRecord | None:
    return CrashRecoveryStore(crash_recovery_path()).load()


def _wait_for_initial_protection(
    *,
    app_process: subprocess.Popen[bytes],
    nft_path: Path,
    sentinel: CrashLeakSentinel,
    timeout: float = 240.0,
) -> tuple[str, CrashRecoveryRecord, KillSwitchStatus]:
    print(
        "\nACTION  In PIA Bazzite, enable the Kill Switch and connect to any server.",
        flush=True,
    )
    print(
        "ACTION  Wait for the green status 'Geschützt'. The test continues automatically.",
        flush=True,
    )
    deadline = time.monotonic() + timeout
    sentinel_started = False
    stable_since: float | None = None
    stable_profile = ""
    stable_record: CrashRecoveryRecord | None = None
    stable_status: KillSwitchStatus | None = None
    verifier = CrashRecoveryVerifier()

    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise CrashHostTestError(
                "PIA Bazzite closed before the Stage-7B protected connection was ready."
            )
        table_document = _read_table_status(nft_path)
        table_present = bool(table_document.get("present"))
        table_verified = bool(table_document.get("verified"))
        problems = tuple(str(value) for value in table_document.get("problems", []))
        if table_present and (not table_verified or problems):
            raise CrashHostTestError(
                "The GUI created an unverified production firewall table: "
                + (", ".join(problems) if problems else "verification failed")
            )
        if table_present and table_verified and not sentinel_started:
            sentinel.start()
            sentinel_started = True
        if sentinel_started:
            sentinel.assert_running_and_clean("the initial protected GUI connection")

        state = network_manager.connection_state()
        try:
            record = _load_record()
        except Exception as exc:
            raise CrashHostTestError(
                f"The Stage-7B crash-recovery record is unsafe or unreadable: {exc}"
            ) from exc

        if table_present and table_verified and state.connected and record is not None:
            status = _kill_switch_status(table_document)
            decision = verifier.evaluate(
                record=record,
                helper_status=status,
                vpn_connected=True,
                active_profile_uuid=state.uuid,
            )
            if decision.disposition == CrashRecoveryDisposition.ADOPT_CONNECTED:
                if state.uuid != stable_profile or record != stable_record:
                    stable_profile = state.uuid
                    stable_record = record
                    stable_status = status
                    stable_since = time.monotonic()
                elif stable_since is not None and time.monotonic() - stable_since >= 2.0:
                    sentinel.assert_running_and_clean(
                        "the stable protected GUI connection and persisted recovery record",
                        announce=True,
                    )
                    print(
                        "PASS    The GUI persisted a private crash-recovery record that "
                        "exactly matches NetworkManager and the verified firewall route.",
                        flush=True,
                    )
                    return stable_profile, stable_record, stable_status
            else:
                stable_since = None
                stable_profile = ""
                stable_record = None
                stable_status = None
        else:
            stable_since = None
            stable_profile = ""
            stable_record = None
            stable_status = None
        time.sleep(0.1)

    raise CrashHostTestError(
        "Timed out waiting for a stable protected GUI connection with an exact recovery record."
    )


def _wait_for_process_and_instance_exit(
    app_process: subprocess.Popen[bytes],
    *,
    timeout: float = 15.0,
) -> None:
    try:
        returncode = app_process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CrashHostTestError("The GUI process did not terminate after SIGKILL.") from exc
    if returncode not in {-signal.SIGKILL, 128 + signal.SIGKILL}:
        raise CrashHostTestError(
            f"The GUI process returned unexpected status {returncode} after SIGKILL."
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not instance_is_running(__app_id__, timeout_ms=250):
            return
        time.sleep(0.1)
    raise CrashHostTestError(
        "The PIA Bazzite single-instance socket remained active after the GUI crash."
    )


def _verify_protection_after_crash(
    *,
    profile_uuid: str,
    expected_record: CrashRecoveryRecord,
    nft_path: Path,
    sentinel: CrashLeakSentinel,
    minimum_seconds: float = 5.0,
) -> None:
    verifier = CrashRecoveryVerifier()
    deadline = time.monotonic() + minimum_seconds
    initial_iterations = sentinel.assert_running_and_clean(
        "the immediate GUI crash boundary"
    )
    while time.monotonic() < deadline:
        state = network_manager.connection_state()
        if not state.connected or state.uuid != profile_uuid:
            raise CrashHostTestError(
                "The protected NetworkManager profile did not remain active after the GUI crash."
            )
        status = _require_verified_lock(nft_path, "the post-crash hold interval")
        record = _load_record()
        if record != expected_record:
            raise CrashHostTestError(
                "The crash-recovery record changed or disappeared after SIGKILL."
            )
        decision = verifier.evaluate(
            record=record,
            helper_status=status,
            vpn_connected=True,
            active_profile_uuid=state.uuid,
        )
        if decision.disposition != CrashRecoveryDisposition.ADOPT_CONNECTED:
            raise CrashHostTestError(
                "The post-crash host state no longer exactly matches the saved record: "
                + decision.reason
            )
        sentinel.assert_running_and_clean("the post-crash protected hold interval")
        time.sleep(0.15)
    final_iterations = sentinel.assert_running_and_clean(
        "the complete post-crash protected hold interval",
        announce=True,
    )
    if final_iterations <= initial_iterations:
        raise CrashHostTestError(
            "The independent sentinel produced no new sample after the GUI was killed."
        )
    print(
        "PASS    VPN, exact firewall route, and private recovery record remained "
        "unchanged after the GUI process was killed.",
        flush=True,
    )


def _terminate_process(process: subprocess.Popen[bytes], *, force: bool) -> None:
    if process.poll() is not None:
        return
    try:
        os.kill(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.kill(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=5)


def main() -> int:
    if not APP_PYTHON.is_file() or not os.access(APP_PYTHON, os.X_OK):
        print("ERROR: .venv/bin/python is missing.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if not APP_MAIN.is_file() or not SENTINEL_PATH.is_file():
        print("ERROR: Required Stage-7B project files are missing.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if instance_is_running(__app_id__, timeout_ms=500):
        print("ERROR: A PIA Bazzite instance is already running.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if network_manager.connection_state().connected:
        print("ERROR: PIA Bazzite is already connected.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if crash_recovery_path().exists() or crash_recovery_path().is_symlink():
        print(
            "ERROR: A previous crash-recovery record exists. Run the Stage-7B reset/preflight first.",
            file=sys.stderr,
        )
        return EXIT_SAFE_FAILURE

    nft_path = _nft_path()
    initial_status = _read_table_status(nft_path)
    if bool(initial_status.get("present")):
        print(
            "ERROR: A previous production firewall lock exists before the Stage-7B driver.",
            file=sys.stderr,
        )
        return EXIT_SAFE_FAILURE

    baseline = NetworkProbeBaseline.capture()
    interface = discover_physical_interface(f"{IPV4_TEST_ADDRESS}:443")
    sentinel = CrashLeakSentinel(interface=interface, baseline=baseline)
    sentinel.prove_direct_baseline()

    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    if instance_is_running(__app_id__, timeout_ms=500):
        print(
            "ERROR: A PIA Bazzite instance appeared immediately before launch.",
            file=sys.stderr,
        )
        return EXIT_SAFE_FAILURE

    app_process = subprocess.Popen(
        [str(APP_PYTHON), str(APP_MAIN)],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_observed = False
    try:
        profile_uuid, record, _status = _wait_for_initial_protection(
            app_process=app_process,
            nft_path=nft_path,
            sentinel=sentinel,
        )
        lock_observed = True
        public_before = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Protected public IP before SIGKILL: "
            + mask_ip_address(public_before.ip_address),
            flush=True,
        )

        print("\n--- Hard GUI crash while protection is active ---", flush=True)
        print(
            f"INFO    Sending SIGKILL to the exact PIA Bazzite GUI process PID {app_process.pid}.",
            flush=True,
        )
        os.kill(app_process.pid, signal.SIGKILL)
        _wait_for_process_and_instance_exit(app_process)
        print("PASS    The exact GUI process was terminated by SIGKILL.", flush=True)

        _verify_protection_after_crash(
            profile_uuid=profile_uuid,
            expected_record=record,
            nft_path=nft_path,
            sentinel=sentinel,
        )
        public_after = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Protected public IP remained reachable after SIGKILL: "
            + mask_ip_address(public_after.ip_address),
            flush=True,
        )
        sentinel.stop_and_assert_clean()
        print("\nALL STAGE-7B REAL GUI SIGKILL PERSISTENCE TESTS PASSED", flush=True)
        print(
            "The GUI is intentionally dead while VPN, firewall, and the recovery record "
            "remain active for the wrapper's deliberate cleanup.",
            flush=True,
        )
        return 0
    except Exception as exc:
        if not lock_observed:
            try:
                lock_observed = bool(_read_table_status(nft_path).get("present"))
            except Exception:
                lock_observed = True
        _terminate_process(app_process, force=lock_observed)
        sentinel.stop_without_assertion()
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return EXIT_FIREWALL_RETAINED if lock_observed else EXIT_SAFE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
