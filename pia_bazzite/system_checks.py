from __future__ import annotations

import shutil
import subprocess

from .credentials import keyring_available
from .models import SystemCheck


def _network_manager_running() -> tuple[bool, str]:
    if shutil.which("nmcli") is None:
        return False, "nmcli not found"
    try:
        completed = subprocess.run(
            ["nmcli", "-t", "-f", "STATE", "general"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout).strip()
    return True, completed.stdout.strip() or "NetworkManager reachable"


def run_system_checks() -> list[SystemCheck]:
    nm_ok, nm_detail = _network_manager_running()
    wg_path = shutil.which("wg")
    ip_path = shutil.which("ip")
    keyring_ok, keyring_detail = keyring_available()
    return [
        SystemCheck("network_manager", nm_ok, nm_detail),
        SystemCheck("wireguard", wg_path is not None, wg_path or "wg not found"),
        SystemCheck("ipv6", ip_path is not None, ip_path or "ip not found"),
        SystemCheck("keyring", keyring_ok, keyring_detail, required=False),
    ]


def required_checks_pass(checks: list[SystemCheck]) -> bool:
    return all(check.ok for check in checks if check.required)
