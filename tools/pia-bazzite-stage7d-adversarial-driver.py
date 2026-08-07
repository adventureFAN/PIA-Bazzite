#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGE7B_DRIVER = ROOT / "tools" / "pia-bazzite-stage7b-crash-driver.py"
STAGE7C4_DRIVER = ROOT / "tools" / "pia-bazzite-stage7c4-takeover-driver.py"
STAGE7D_RESET = ROOT / "tools" / "kill-switch-crash-stage7d-emergency-reset.sh"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load required test boundary: {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


stage7b = _load_module("pia_stage7b_crash_driver_stage7d", STAGE7B_DRIVER)
stage7c4 = _load_module("pia_stage7c4_takeover_driver_stage7d", STAGE7C4_DRIVER)

from pia_bazzite import __app_id__, network_manager
from pia_bazzite.kill_switch_crash_state import CrashRecoveryStore
from pia_bazzite.kill_switch_session import KillSwitchSessionClient
from pia_bazzite.logging_utils import mask_ip_address
from pia_bazzite.network_paths import discover_physical_interface
from pia_bazzite.network_probes import IPV4_TEST_ADDRESS, NetworkProbeBaseline
from pia_bazzite.pia_api import fetch_public_network_info
from pia_bazzite.settings import create_settings, crash_recovery_path
from pia_bazzite.single_instance import instance_is_running


EXIT_SAFE_FAILURE = stage7b.EXIT_SAFE_FAILURE
EXIT_FIREWALL_RETAINED = stage7b.EXIT_FIREWALL_RETAINED
SYNTHETIC_ENDPOINT = "192.0.2.1:1337"
CORRUPT_RECORD = b'{"kind":"pia-bazzite-kill-switch-crash-recovery","schema_version":1,"checksum":"stage7d-tampered"}\n'


class Stage7DHostTestError(stage7b.CrashHostTestError):
    pass


def _assert_clean_host(nft_path: Path, label: str) -> None:
    if network_manager.connection_state().connected:
        raise Stage7DHostTestError(f"PIA VPN unexpectedly connected during {label}.")
    if bool(stage7b._read_table_status(nft_path).get("present")):
        raise Stage7DHostTestError(
            f"Production firewall table unexpectedly present during {label}."
        )


def _write_corrupt_private_record() -> bytes:
    path = crash_recovery_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise Stage7DHostTestError(
            "A crash-recovery path already exists before the corruption scenario."
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, CORRUPT_RECORD)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600, follow_symlinks=False)
    return path.read_bytes()


def _observe_corrupt_record_refusal(
    app_process: subprocess.Popen[bytes],
    *,
    nft_path: Path,
    original_bytes: bytes,
    minimum_seconds: float = 4.0,
) -> None:
    deadline = time.monotonic() + minimum_seconds
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise Stage7DHostTestError(
                f"The GUI exited while refusing the corrupted recovery record ({app_process.returncode})."
            )
        _assert_clean_host(nft_path, "corrupted-record refusal")
        path = crash_recovery_path()
        if not path.is_file() or path.is_symlink():
            raise Stage7DHostTestError(
                "The corrupted recovery record disappeared before a verified host release cleanup."
            )
        if path.read_bytes() != original_bytes:
            raise Stage7DHostTestError(
                "The GUI modified the corrupted recovery record during startup refusal."
            )
        probe = stage7c4._privileged_session_pipe_probe(app_process.pid)
        if probe.binding is not None:
            raise Stage7DHostTestError(
                "The GUI opened a privileged helper session even though recovery-record parsing failed first."
            )
        time.sleep(0.2)
    print(
        "PASS    A corrupted private recovery record was refused before privilege, VPN, or firewall activity and remained unchanged.",
        flush=True,
    )


def _discard_corrupt_record_after_clean_host_proof(nft_path: Path) -> None:
    _assert_clean_host(nft_path, "verified corrupt-record cleanup")
    store = CrashRecoveryStore(crash_recovery_path())
    store.discard_untrusted_after_verified_release()
    path = crash_recovery_path()
    if path.exists() or path.is_symlink():
        raise Stage7DHostTestError(
            "The corrupted recovery path remained after verified-release cleanup."
        )
    print(
        "PASS    Verified-release cleanup removed only the untrusted recovery pathname after the host was independently clean.",
        flush=True,
    )


def _create_unowned_verified_lock(interface: str, nft_path: Path) -> None:
    print(
        "ACTION  Authenticate the Stage-7D helper session that creates the deliberate unowned firewall lock if prompted.",
        flush=True,
    )
    session = KillSwitchSessionClient(timeout=120.0)
    try:
        session.open()
        status = session.enable(
            interfaces=(interface,),
            endpoints=(SYNTHETIC_ENDPOINT,),
        )
        if not status.protection_active:
            raise Stage7DHostTestError(
                "The deliberate unowned firewall lock was not verified after enable."
            )
        if status.physical_interfaces != (interface,):
            raise Stage7DHostTestError(
                "The deliberate unowned lock has an unexpected physical-interface allowlist."
            )
        if status.endpoints != (SYNTHETIC_ENDPOINT,):
            raise Stage7DHostTestError(
                "The deliberate unowned lock has an unexpected endpoint allowlist."
            )
    finally:
        try:
            session.close()
        except Exception:
            pass

    live = stage7b._require_verified_lock(nft_path, "deliberate unowned-lock setup")
    if live.physical_interfaces != (interface,) or live.endpoints != (SYNTHETIC_ENDPOINT,):
        raise Stage7DHostTestError(
            "The production table changed after closing the setup helper session."
        )
    if network_manager.connection_state().connected:
        raise Stage7DHostTestError(
            "The PIA VPN unexpectedly connected while creating the unowned lock."
        )
    path = crash_recovery_path()
    if path.exists() or path.is_symlink():
        raise Stage7DHostTestError(
            "A recovery record appeared while creating an intentionally unowned lock."
        )
    print(
        "PASS    A verified production firewall lock exists without VPN or recovery record; closing the setup helper did not open it.",
        flush=True,
    )


def _observe_unowned_lock_refusal(
    app_process: subprocess.Popen[bytes],
    *,
    nft_path: Path,
    sentinel: stage7b.CrashLeakSentinel,
    interface: str,
    minimum_seconds: float = 5.0,
) -> None:
    print(
        "ACTION  Authenticate the automatic startup protection check for the unowned lock if prompted.",
        flush=True,
    )
    print(
        "ACTION  Do not press reconnect or protection-status buttons; the GUI must refuse automatic takeover.",
        flush=True,
    )
    deadline = time.monotonic() + 180.0
    stable_pid: int | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if app_process.poll() is not None:
            raise Stage7DHostTestError(
                f"The GUI exited while refusing the unowned lock ({app_process.returncode})."
            )
        if network_manager.connection_state().connected:
            raise Stage7DHostTestError(
                "The GUI connected the VPN while an unowned firewall lock was being refused."
            )
        path = crash_recovery_path()
        if path.exists() or path.is_symlink():
            raise Stage7DHostTestError(
                "The GUI fabricated a recovery record for an unowned firewall lock."
            )
        live = stage7b._require_verified_lock(nft_path, "unowned-lock refusal")
        if live.physical_interfaces != (interface,) or live.endpoints != (SYNTHETIC_ENDPOINT,):
            raise Stage7DHostTestError(
                "The GUI changed the exact firewall route while refusing the unowned lock."
            )
        sentinel.assert_running_and_clean("unowned-lock startup refusal")
        probe = stage7c4._privileged_session_pipe_probe(app_process.pid)
        binding = probe.binding
        if binding is None:
            stable_pid = None
            stable_since = None
        elif binding.pid != stable_pid:
            stable_pid = binding.pid
            stable_since = time.monotonic()
        elif stable_since is not None and time.monotonic() - stable_since >= minimum_seconds:
            sentinel.assert_running_and_clean(
                "stable refused unowned-lock state",
                announce=True,
            )
            print(
                "PASS    The GUI retained a read-only authenticated helper session but refused to adopt or modify the unowned lock.",
                flush=True,
            )
            return
        time.sleep(0.15)
    raise Stage7DHostTestError(
        "Timed out waiting for a stable fail-closed refusal of the unowned production lock."
    )


def _run_verified_emergency_reset() -> None:
    completed = subprocess.run(
        ["bash", str(STAGE7D_RESET)],
        cwd=str(ROOT),
        text=True,
        check=False,
        timeout=180.0,
    )
    if completed.returncode != 0:
        raise Stage7DHostTestError(
            f"The Stage-7D emergency reset failed with status {completed.returncode}."
        )


def main() -> int:
    for required in (stage7b.APP_PYTHON, stage7b.APP_MAIN, STAGE7D_RESET):
        if not required.is_file():
            print(f"ERROR: Required Stage-7D file is missing: {required}", file=sys.stderr)
            return EXIT_SAFE_FAILURE
    if not os.access(stage7b.APP_PYTHON, os.X_OK):
        print("ERROR: .venv/bin/python is not executable.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if instance_is_running(__app_id__, timeout_ms=500):
        print("ERROR: A PIA Bazzite instance is already running.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    if network_manager.connection_state().connected:
        print("ERROR: PIA Bazzite is already connected.", file=sys.stderr)
        return EXIT_SAFE_FAILURE

    nft_path = stage7b._nft_path()
    if bool(stage7b._read_table_status(nft_path).get("present")):
        print("ERROR: A previous production firewall lock exists.", file=sys.stderr)
        return EXIT_SAFE_FAILURE
    path = crash_recovery_path()
    if path.exists() or path.is_symlink():
        print("ERROR: A previous crash-recovery path exists.", file=sys.stderr)
        return EXIT_SAFE_FAILURE

    settings = create_settings()
    settings.setValue("kill_switch/enabled", True)
    settings.sync()
    print("PASS    Kill Switch preference is enabled for the Stage-7D startup checks.", flush=True)

    corrupt_app: subprocess.Popen[bytes] | None = None
    refusal_app: subprocess.Popen[bytes] | None = None
    clean_app: subprocess.Popen[bytes] | None = None
    sentinel: stage7b.CrashLeakSentinel | None = None
    lock_observed = False
    try:
        print("\n--- Adversarial stale-record refusal on a clean host ---", flush=True)
        original = _write_corrupt_private_record()
        corrupt_app = stage7c4._launch_app()
        _observe_corrupt_record_refusal(
            corrupt_app,
            nft_path=nft_path,
            original_bytes=original,
        )
        stage7b._terminate_process(corrupt_app, force=False)
        corrupt_app = None
        _discard_corrupt_record_after_clean_host_proof(nft_path)

        print("\n--- Verified unowned-lock refusal under independent leak observation ---", flush=True)
        baseline = NetworkProbeBaseline.capture()
        interface = discover_physical_interface(f"{IPV4_TEST_ADDRESS}:443")
        _create_unowned_verified_lock(interface, nft_path)
        lock_observed = True
        sentinel = stage7b.CrashLeakSentinel(interface=interface, baseline=baseline)
        sentinel.start()
        refusal_app = stage7c4._launch_app()
        _observe_unowned_lock_refusal(
            refusal_app,
            nft_path=nft_path,
            sentinel=sentinel,
            interface=interface,
        )
        sentinel.stop_and_assert_clean()
        sentinel = None

        print("\n--- Deliberate Stage-7D Emergency Reset and clean restart ---", flush=True)
        _run_verified_emergency_reset()
        lock_observed = False
        _assert_clean_host(nft_path, "post-reset verification")
        if path.exists() or path.is_symlink():
            raise Stage7DHostTestError(
                "A crash-recovery path remains after the Stage-7D emergency reset."
            )
        normal_info = fetch_public_network_info(timeout=12.0)
        print(
            "PASS    Normal public network access returned after the verified emergency reset: "
            + mask_ip_address(normal_info.ip_address),
            flush=True,
        )

        stage7b._terminate_process(refusal_app, force=False)
        refusal_app = None
        clean_app = stage7c4._launch_app()
        stage7c4._wait_for_clean_startup_reconciliation(clean_app, nft_path=nft_path)
        _assert_clean_host(nft_path, "clean restart after refused takeover and reset")
        if path.exists() or path.is_symlink():
            raise Stage7DHostTestError(
                "A recovery record appeared on the clean restart after emergency reset."
            )
        print(
            "PASS    After the refused takeover and Emergency Reset, a fresh GUI start reconciled automatically without the manual status button.",
            flush=True,
        )
        stage7b._terminate_process(clean_app, force=False)
        clean_app = None

        print("\nALL STAGE-7D ADVERSARIAL RECOVERY AND EMERGENCY-RESET TESTS PASSED", flush=True)
        return 0
    except Exception as exc:
        try:
            lock_observed = lock_observed or bool(
                stage7b._read_table_status(nft_path).get("present")
            )
        except Exception:
            lock_observed = True
        if sentinel is not None:
            sentinel.stop_without_assertion()
        for process in (clean_app, refusal_app, corrupt_app):
            if process is not None:
                stage7b._terminate_process(process, force=lock_observed)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return EXIT_FIREWALL_RETAINED if lock_observed else EXIT_SAFE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
