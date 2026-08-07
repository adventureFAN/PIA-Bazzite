#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGE7B_DRIVER = ROOT / "tools" / "pia-bazzite-stage7b-crash-driver.py"

spec = importlib.util.spec_from_file_location("pia_stage7b_crash_driver", STAGE7B_DRIVER)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load the verified Stage-7B crash driver boundary.")
stage7b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage7b)

from pia_bazzite import __app_id__, network_manager
from pia_bazzite.kill_switch_crash_state import (
    CrashRecoveryDisposition,
    CrashRecoveryRecord,
    CrashRecoveryVerifier,
)
from pia_bazzite.logging_utils import mask_ip_address
from pia_bazzite.network_paths import discover_physical_interface
from pia_bazzite.network_probes import IPV4_TEST_ADDRESS, NetworkProbeBaseline
from pia_bazzite.pia_api import fetch_public_network_info
from pia_bazzite.settings import create_settings, crash_recovery_path
from pia_bazzite.single_instance import instance_is_running


EXIT_SAFE_FAILURE = stage7b.EXIT_SAFE_FAILURE
EXIT_FIREWALL_RETAINED = stage7b.EXIT_FIREWALL_RETAINED
APP_PYTHON = stage7b.APP_PYTHON
APP_MAIN = stage7b.APP_MAIN
SESSION_HELPER = "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-session"
SUDO_PATH = Path("/usr/bin/sudo")
SYSTEM_PYTHON = Path("/usr/bin/python3")

_PRIVILEGED_SESSION_PROBE = r"""
from pathlib import Path
import json
import os
import sys

app_pid = int(sys.argv[1])
needle = sys.argv[2]


def parent_of(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    closing = raw.rfind(")")
    if closing < 0:
        return 0
    fields = raw[closing + 2 :].split()
    return int(fields[1]) if len(fields) > 1 else 0


def descends_from(pid: int) -> bool:
    seen = set()
    current = pid
    for _ in range(32):
        if current == app_pid:
            return True
        if current <= 1 or current in seen:
            return False
        seen.add(current)
        try:
            current = parent_of(current)
        except (OSError, ValueError):
            return False
    return False


def pipe_fds(pid: int) -> dict[str, str]:
    result = {}
    directory = Path(f"/proc/{pid}/fd")
    try:
        entries = list(directory.iterdir())
    except OSError:
        return result
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("pipe:["):
            result[entry.name] = target
    return result


app_pipes = pipe_fds(app_pid)
app_pipe_values = set(app_pipes.values())
candidates = []
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    pid = int(entry.name)
    try:
        cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
    except OSError:
        continue
    if needle not in cmdline:
        continue
    helper_pipes = pipe_fds(pid)
    stdio = [helper_pipes.get(str(fd), "") for fd in (0, 1, 2)]
    shared = sorted(set(helper_pipes.values()) & app_pipe_values)
    pipe_bound = (
        len(set(stdio)) == 3
        and all(value.startswith("pipe:[") for value in stdio)
        and all(value in app_pipe_values for value in stdio)
    )
    try:
        ppid = parent_of(pid)
    except (OSError, ValueError):
        ppid = 0
    candidates.append(
        {
            "pid": pid,
            "ppid": ppid,
            "descendant": descends_from(pid),
            "stdio_pipes": stdio,
            "shared_pipes": shared,
            "pipe_bound": pipe_bound,
        }
    )

print(
    json.dumps(
        {
            "app_pid": app_pid,
            "app_pipe_count": len(app_pipe_values),
            "candidates": candidates,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
"""


@dataclass(frozen=True, slots=True)
class SessionPipeBinding:
    pid: int
    ppid: int
    descendant: bool
    stdio_pipes: tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class SessionPipeProbe:
    binding: SessionPipeBinding | None
    summary: str


class TakeoverHostTestError(stage7b.CrashHostTestError):
    pass


def _launch_app() -> subprocess.Popen[bytes]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    return subprocess.Popen(
        [str(APP_PYTHON), str(APP_MAIN)],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _privileged_session_pipe_probe(app_pid: int) -> SessionPipeProbe:
    """Prove ownership by the three live stdio pipes, not process ancestry."""

    completed = subprocess.run(
        [
            str(SUDO_PATH),
            "-n",
            str(SYSTEM_PYTHON),
            "-I",
            "-c",
            _PRIVILEGED_SESSION_PROBE,
            str(app_pid),
            SESSION_HELPER,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5.0,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise TakeoverHostTestError(
            "The privileged restricted-session pipe probe failed"
            + (f": {detail}" if detail else ".")
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise TakeoverHostTestError(
            "The privileged restricted-session pipe probe returned malformed JSON."
        ) from exc
    if not isinstance(document, dict) or document.get("app_pid") != app_pid:
        raise TakeoverHostTestError(
            "The privileged restricted-session pipe probe returned an invalid envelope."
        )
    raw_candidates = document.get("candidates")
    if not isinstance(raw_candidates, list):
        raise TakeoverHostTestError(
            "The privileged restricted-session pipe probe omitted its candidates."
        )

    bindings: list[SessionPipeBinding] = []
    summaries: list[str] = []
    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            continue
        pid = candidate.get("pid")
        ppid = candidate.get("ppid")
        descendant = candidate.get("descendant")
        stdio = candidate.get("stdio_pipes")
        shared = candidate.get("shared_pipes")
        pipe_bound = candidate.get("pipe_bound")
        summaries.append(
            f"pid={pid},ppid={ppid},descendant={descendant},"
            f"pipe_bound={pipe_bound},shared={shared}"
        )
        if (
            isinstance(pid, int)
            and pid > 1
            and isinstance(ppid, int)
            and isinstance(descendant, bool)
            and pipe_bound is True
            and isinstance(stdio, list)
            and len(stdio) == 3
            and all(isinstance(value, str) and value.startswith("pipe:[") for value in stdio)
        ):
            bindings.append(
                SessionPipeBinding(
                    pid=pid,
                    ppid=ppid,
                    descendant=descendant,
                    stdio_pipes=(stdio[0], stdio[1], stdio[2]),
                )
            )
    if len(bindings) > 1:
        raise TakeoverHostTestError(
            "More than one restricted helper is pipe-bound to the same GUI process."
        )
    summary = "; ".join(summaries) if summaries else "no matching helper process"
    return SessionPipeProbe(
        binding=bindings[0] if bindings else None,
        summary=summary,
    )


def _wait_for_clean_startup_reconciliation(
    app_process: subprocess.Popen[bytes],
    *,
    nft_path: Path,
    timeout: float = 180.0,
) -> int:
    print(
        "ACTION  Authenticate the automatic startup protection-status check if prompted.",
        flush=True,
    )
    print(
        "ACTION  Do NOT click 'Schutzstatus neu prüfen'. The test requires automatic startup reconciliation.",
        flush=True,
    )
    deadline = time.monotonic() + timeout
    stable_pid: int | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise TakeoverHostTestError(
                f"The first GUI exited during automatic startup reconciliation ({app_process.returncode})."
            )
        if bool(stage7b._read_table_status(nft_path).get("present")):
            raise TakeoverHostTestError(
                "A firewall table appeared before the user started the protected connection."
            )
        if network_manager.connection_state().connected:
            raise TakeoverHostTestError(
                "The VPN connected before clean startup reconciliation was verified."
            )
        if crash_recovery_path().exists() or crash_recovery_path().is_symlink():
            raise TakeoverHostTestError(
                "A crash-recovery record appeared before the protected connection started."
            )
        probe = _privileged_session_pipe_probe(app_process.pid)
        binding = probe.binding
        if binding is not None:
            if binding.pid != stable_pid:
                stable_pid = binding.pid
                stable_since = time.monotonic()
            elif stable_since is not None and time.monotonic() - stable_since >= 1.0:
                print(
                    "PASS    The GUI automatically opened a restricted helper whose three stdio pipes remain owned by the GUI process.",
                    flush=True,
                )
                print(
                    "PASS    No manual protection-status recheck was required before server selection.",
                    flush=True,
                )
                return binding.pid
        else:
            stable_pid = None
            stable_since = None
        time.sleep(0.1)
    raise TakeoverHostTestError(
        "Timed out waiting for the automatic clean-start protection reconciliation."
    )


def _same_recovery_payload(left: CrashRecoveryRecord, right: CrashRecoveryRecord) -> bool:
    return (
        left.phase == right.phase
        and left.profile_uuid == right.profile_uuid
        and left.physical_interfaces == right.physical_interfaces
        and left.endpoints == right.endpoints
    )


def _wait_for_connected_takeover(
    app_process: subprocess.Popen[bytes],
    *,
    previous_record: CrashRecoveryRecord,
    profile_uuid: str,
    nft_path: Path,
    sentinel: stage7b.CrashLeakSentinel,
    timeout: float = 180.0,
) -> CrashRecoveryRecord:
    print(
        "ACTION  Authenticate the automatic startup protection check after the crash.",
        flush=True,
    )
    print(
        "ACTION  Do not press any reconnect or protection-status button; wait for the green 'Geschützt' state.",
        flush=True,
    )
    verifier = CrashRecoveryVerifier()
    deadline = time.monotonic() + timeout
    stable_record: CrashRecoveryRecord | None = None
    stable_session_pid: int | None = None
    stable_since: float | None = None
    rotated_without_session_since: float | None = None
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise TakeoverHostTestError(
                f"The restarted GUI exited before takeover completed ({app_process.returncode})."
            )
        sentinel.assert_running_and_clean("automatic crash-state takeover")
        state = network_manager.connection_state()
        if not state.connected or state.uuid != profile_uuid:
            raise TakeoverHostTestError(
                "The protected NetworkManager profile changed during GUI takeover."
            )
        status = stage7b._require_verified_lock(nft_path, "automatic GUI takeover")
        record = stage7b._load_record()
        if record is None:
            stable_record = None
            stable_session_pid = None
            stable_since = None
            rotated_without_session_since = None
            time.sleep(0.1)
            continue
        decision = verifier.evaluate(
            record=record,
            helper_status=status,
            vpn_connected=True,
            active_profile_uuid=state.uuid,
        )
        adopted = decision.disposition == CrashRecoveryDisposition.ADOPT_CONNECTED
        rotated = record.session_id != previous_record.session_id
        same_payload = _same_recovery_payload(record, previous_record)
        if adopted and rotated and same_payload:
            probe = _privileged_session_pipe_probe(app_process.pid)
            binding = probe.binding
            if binding is None:
                stable_record = None
                stable_session_pid = None
                stable_since = None
                if rotated_without_session_since is None:
                    rotated_without_session_since = time.monotonic()
                elif time.monotonic() - rotated_without_session_since >= 10.0:
                    raise TakeoverHostTestError(
                        "The restarted GUI rotated the recovery record but no restricted helper "
                        "remained bound to all three GUI transport pipes for 10 seconds. "
                        f"Last root probe: {probe.summary}"
                    )
            else:
                rotated_without_session_since = None
                if record != stable_record or binding.pid != stable_session_pid:
                    stable_record = record
                    stable_session_pid = binding.pid
                    stable_since = time.monotonic()
                elif stable_since is not None and time.monotonic() - stable_since >= 2.0:
                    sentinel.assert_running_and_clean(
                        "the stable automatically adopted protected GUI session",
                        announce=True,
                    )
                    print(
                        "PASS    The restarted GUI retained an authenticated helper transport before rotating the recovery record.",
                        flush=True,
                    )
                    relation = "a descendant" if binding.descendant else "reparented but still pipe-bound"
                    print(
                        f"PASS    Root-visible restricted helper PID {binding.pid} is {relation} of restarted GUI PID {app_process.pid}; all three private transport pipes remain attached.",
                        flush=True,
                    )
                    print(
                        "PASS    The restarted GUI exactly matched NetworkManager, firewall route, and recovery record.",
                        flush=True,
                    )
                    print(
                        "PASS    The GUI rotated the recovery session ID only after verified connected-state takeover.",
                        flush=True,
                    )
                    return record
        else:
            stable_record = None
            stable_session_pid = None
            stable_since = None
            rotated_without_session_since = None
        time.sleep(0.1)
    raise TakeoverHostTestError(
        "Timed out waiting for exact automatic takeover of the crash-surviving protection state."
    )


def _wait_for_deliberate_gui_disconnect(
    app_process: subprocess.Popen[bytes],
    *,
    nft_path: Path,
    timeout: float = 180.0,
) -> None:
    print(
        "ACTION  Click the normal VPN disconnect button in the restarted PIA Bazzite window.",
        flush=True,
    )
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise TakeoverHostTestError(
                f"The restarted GUI exited before the deliberate disconnect completed ({app_process.returncode})."
            )
        state = network_manager.connection_state()
        table_present = bool(stage7b._read_table_status(nft_path).get("present"))
        record_present = crash_recovery_path().exists() or crash_recovery_path().is_symlink()
        if not state.connected and not table_present and not record_present:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 2.0:
                print(
                    "PASS    The adopted GUI session completed a verified intentional disconnect and removed the recovery record.",
                    flush=True,
                )
                return
        else:
            stable_since = None
        time.sleep(0.1)
    raise TakeoverHostTestError(
        "Timed out waiting for the restarted GUI to complete the intentional disconnect."
    )


def main() -> int:
    if not APP_PYTHON.is_file() or not os.access(APP_PYTHON, os.X_OK):
        print("ERROR: .venv/bin/python is missing.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if not APP_MAIN.is_file() or not STAGE7B_DRIVER.is_file():
        print("ERROR: Required Stage-7C project files are missing.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if instance_is_running(__app_id__, timeout_ms=500):
        print("ERROR: A PIA Bazzite instance is already running.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if network_manager.connection_state().connected:
        print("ERROR: PIA Bazzite is already connected.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if crash_recovery_path().exists() or crash_recovery_path().is_symlink():
        print("ERROR: A previous crash-recovery record exists.", file=sys.stderr)
        return EXIT_SAFE_FAILURE

    nft_path = stage7b._nft_path()
    if bool(stage7b._read_table_status(nft_path).get("present")):
        print("ERROR: A previous production firewall lock exists.", file=sys.stderr)
        return EXIT_SAFE_FAILURE

    settings = create_settings()
    settings.setValue("kill_switch/enabled", True)
    settings.sync()
    print("PASS    Kill Switch preference is enabled before the clean GUI startup.", flush=True)

    baseline = NetworkProbeBaseline.capture()
    interface = discover_physical_interface(f"{IPV4_TEST_ADDRESS}:443")
    sentinel = stage7b.CrashLeakSentinel(interface=interface, baseline=baseline)
    sentinel.prove_direct_baseline()

    first_app: subprocess.Popen[bytes] | None = None
    second_app: subprocess.Popen[bytes] | None = None
    lock_observed = False
    try:
        first_app = _launch_app()
        _wait_for_clean_startup_reconciliation(first_app, nft_path=nft_path)
        print(
            "ACTION  Select any server and connect. Wait for the green 'Geschützt' state.",
            flush=True,
        )
        profile_uuid, previous_record, _status = stage7b._wait_for_initial_protection(
            app_process=first_app,
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

        print("\n--- Hard crash followed by automatic GUI takeover ---", flush=True)
        print(
            f"INFO    Sending SIGKILL to the exact first GUI process PID {first_app.pid}.",
            flush=True,
        )
        os.kill(first_app.pid, signal.SIGKILL)
        stage7b._wait_for_process_and_instance_exit(first_app)
        print("PASS    The first GUI process was terminated by SIGKILL.", flush=True)
        stage7b._verify_protection_after_crash(
            profile_uuid=profile_uuid,
            expected_record=previous_record,
            nft_path=nft_path,
            sentinel=sentinel,
            minimum_seconds=3.0,
        )

        second_app = _launch_app()
        adopted_record = _wait_for_connected_takeover(
            second_app,
            previous_record=previous_record,
            profile_uuid=profile_uuid,
            nft_path=nft_path,
            sentinel=sentinel,
        )
        if adopted_record.session_id == previous_record.session_id:
            raise TakeoverHostTestError("The recovery session ID was not rotated.")
        public_after = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Protected public IP remained reachable after automatic takeover: "
            + mask_ip_address(public_after.ip_address),
            flush=True,
        )
        sentinel.stop_and_assert_clean()

        _wait_for_deliberate_gui_disconnect(second_app, nft_path=nft_path)
        normal_info = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Normal public network access returned after the deliberate GUI disconnect: "
            + mask_ip_address(normal_info.ip_address),
            flush=True,
        )
        print("\nALL STAGE-7C REAL GUI CRASH-TAKEOVER TESTS PASSED", flush=True)
        print(
            "The restarted GUI remains open, disconnected, and ready for normal use.",
            flush=True,
        )
        return 0
    except Exception as exc:
        try:
            lock_observed = lock_observed or bool(
                stage7b._read_table_status(nft_path).get("present")
            )
        except Exception:
            lock_observed = True
        for process in (second_app, first_app):
            if process is not None:
                stage7b._terminate_process(process, force=lock_observed)
        sentinel.stop_without_assertion()
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return EXIT_FIREWALL_RETAINED if lock_observed else EXIT_SAFE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
