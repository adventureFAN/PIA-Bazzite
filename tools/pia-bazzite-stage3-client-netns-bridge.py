#!/usr/bin/python3 -I
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Mapping, Sequence

TARGET_PATTERN = re.compile(
    r"/(?:usr/local|var/usrlocal)/libexec/pia-bazzite/"
    r"pia-bazzite-stage3-client-netns-bridge-([0-9]{1,10})\Z"
)
HELPER_PATH = Path("/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper")
IP_PATH = Path("/usr/bin/ip")
NETNS_ROOT = Path("/run/netns")
NAMESPACE_PREFIX = "pia-h3-client-"

# The bridge accepts the same protocol argv emitted by KillSwitchClient, but
# only for this fixed laboratory scenario. Every accepted request is listed
# literally; callers cannot choose table names, arbitrary interfaces, commands,
# executable paths, or endpoints outside the lab.
ALLOWED_REQUESTS: dict[str, tuple[str, ...]] = {
    "status": (),
    "enable": (
        "--interface", "wan0",
        "--endpoint", "198.51.100.10:1337",
        "--endpoint", "[2001:db8:100::10]:1337",
    ),
    "set-endpoints": (
        "--endpoint", "198.51.100.11:1443",
        "--endpoint", "[2001:db8:100::11]:1443",
    ),
    "set-interfaces": ("--interface", "lan0"),
    "add-endpoint": ("--endpoint", "198.51.100.10:1337"),
    "remove-endpoint": ("--endpoint", "198.51.100.10:1337"),
    "disable": (),
    "emergency-reset": (),
}

EXIT_USAGE = 2
EXIT_PRIVILEGE = 3
EXIT_SAFETY = 4


class BridgeError(RuntimeError):
    def __init__(self, kind: str, message: str, code: int) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code


def _emit_error(error: BridgeError) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "bridge": "stage3-client-netns-test",
                "error": error.kind,
                "message": str(error),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return error.code


def parse_request(argv: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    if not argv:
        raise BridgeError("usage", "A fixed helper action is required.", EXIT_USAGE)
    action = argv[0]
    expected = ALLOWED_REQUESTS.get(action)
    if expected is None or tuple(argv[1:]) != expected:
        raise BridgeError(
            "validation",
            "Request is outside the fixed stage-3 client laboratory scope.",
            EXIT_USAGE,
        )
    return action, expected


def _verify_root_owned_file(path: Path, expected_mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BridgeError(
            "installation", f"Could not inspect {path}: {exc}", EXIT_SAFETY
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise BridgeError("installation", f"Expected a regular file: {path}", EXIT_SAFETY)
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise BridgeError("installation", f"File is not root:root: {path}", EXIT_SAFETY)
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise BridgeError(
            "installation", f"File mode is not {expected_mode:04o}: {path}", EXIT_SAFETY
        )
    if metadata.st_nlink != 1:
        raise BridgeError("installation", f"File has multiple hard links: {path}", EXIT_SAFETY)


def verify_execution_boundary(
    launcher_path: Path,
    environment: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    if os.geteuid() != 0:
        raise BridgeError(
            "privilege",
            "The test bridge must run through an authorized root boundary.",
            EXIT_PRIVILEGE,
        )
    env = os.environ if environment is None else environment
    raw_uid = env.get("PKEXEC_UID")
    if raw_uid is None or not raw_uid.isascii() or not raw_uid.isdecimal():
        raise BridgeError("privilege", "PKEXEC_UID is missing or invalid.", EXIT_PRIVILEGE)
    invoking_uid = int(raw_uid, 10)
    if invoking_uid <= 0:
        raise BridgeError("privilege", "Authorized caller must be non-root.", EXIT_PRIVILEGE)

    try:
        actual_bridge = launcher_path.resolve(strict=True)
        helper = HELPER_PATH.resolve(strict=True)
        ip_binary = IP_PATH.resolve(strict=True)
    except OSError as exc:
        raise BridgeError("installation", f"Could not resolve fixed path: {exc}", EXIT_SAFETY) from exc

    match = TARGET_PATTERN.fullmatch(str(actual_bridge))
    if match is None:
        raise BridgeError("installation", "Bridge is not running from its fixed test path.", EXIT_SAFETY)
    token = match.group(1)
    expected_bridge = Path(match.group(0))
    _verify_root_owned_file(expected_bridge, 0o755)
    _verify_root_owned_file(helper, 0o755)
    _verify_root_owned_file(ip_binary, 0o755)

    namespace = NAMESPACE_PREFIX + token
    namespace_path = NETNS_ROOT / namespace
    try:
        metadata = namespace_path.lstat()
    except OSError as exc:
        raise BridgeError("namespace", f"Could not inspect test namespace: {exc}", EXIT_SAFETY) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise BridgeError("namespace", "Test namespace must not be a symlink.", EXIT_SAFETY)
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise BridgeError("namespace", "Test namespace is not root:root.", EXIT_SAFETY)
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise BridgeError("namespace", "Test namespace is writable by group or world.", EXIT_SAFETY)
    return invoking_uid, namespace


def sanitized_environment(invoking_uid: int) -> dict[str, str]:
    return {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C",
        "PKEXEC_UID": str(invoking_uid),
    }


def build_exec_argv(namespace: str, action: str, arguments: Sequence[str]) -> list[str]:
    return [
        str(IP_PATH),
        "netns",
        "exec",
        namespace,
        str(HELPER_PATH),
        action,
        *arguments,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        action, fixed_arguments = parse_request(arguments)
        invoking_uid, namespace = verify_execution_boundary(Path(sys.argv[0]))
        os.execve(
            str(IP_PATH),
            build_exec_argv(namespace, action, fixed_arguments),
            sanitized_environment(invoking_uid),
        )
    except BridgeError as exc:
        return _emit_error(exc)
    except OSError as exc:
        return _emit_error(
            BridgeError("execution", f"Could not enter test namespace: {exc}", EXIT_SAFETY)
        )
    return EXIT_SAFETY


if __name__ == "__main__":
    raise SystemExit(main())
