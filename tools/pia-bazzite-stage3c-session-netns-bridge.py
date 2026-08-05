#!/usr/bin/python3 -I
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Mapping

TARGET_PATTERN = re.compile(
    r"/(?:usr/local|var/usrlocal)/libexec/pia-bazzite/"
    r"pia-bazzite-stage3c-session-netns-bridge-([0-9]{1,10})\Z"
)
SESSION_PATH = Path(
    "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-session"
)
IP_PATH = Path("/usr/bin/ip")
NETNS_ROOT = Path("/run/netns")
NAMESPACE_PREFIX = "pia-h3c-client-"

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
                "bridge": "stage3c-session-netns-test",
                "error": error.kind,
                "message": str(error),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return error.code


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
        session = SESSION_PATH.resolve(strict=True)
        ip_binary = IP_PATH.resolve(strict=True)
    except OSError as exc:
        raise BridgeError("installation", f"Could not resolve fixed path: {exc}", EXIT_SAFETY) from exc

    match = TARGET_PATTERN.fullmatch(str(actual_bridge))
    if match is None:
        raise BridgeError("installation", "Bridge is not running from its fixed test path.", EXIT_SAFETY)
    token = match.group(1)
    _verify_root_owned_file(Path(match.group(0)), 0o755)
    _verify_root_owned_file(session, 0o755)
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


def build_exec_argv(namespace: str) -> list[str]:
    return [
        str(IP_PATH),
        "netns",
        "exec",
        namespace,
        str(SESSION_PATH),
    ]


def main() -> int:
    if len(sys.argv) != 1:
        return _emit_error(
            BridgeError("usage", "The fixed session bridge accepts no arguments.", EXIT_USAGE)
        )
    try:
        invoking_uid, namespace = verify_execution_boundary(Path(sys.argv[0]))
        os.execve(
            str(IP_PATH),
            build_exec_argv(namespace),
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
