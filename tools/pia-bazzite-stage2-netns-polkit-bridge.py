#!/usr/bin/python3 -I
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Mapping, Sequence

BRIDGE_PATH = Path("/usr/local/libexec/pia-bazzite/pia-bazzite-stage2-netns-test-bridge")
HELPER_PATH = Path("/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper")
IP_PATH = Path("/usr/bin/ip")
NETNS_ROOT = Path("/run/netns")
NAMESPACE_PATTERN = re.compile(r"pia-h2-client-[0-9]{1,10}\Z")
FIXED_HELPER_ARGUMENTS = (
    "enable", "--interface", "wan0",
    "--endpoint", "198.51.100.1:1337",
    "--endpoint", "[2001:db8:10::1]:1337",
)
EXIT_USAGE = 2
EXIT_PRIVILEGE = 3
EXIT_SAFETY = 4


class BridgeError(RuntimeError):
    def __init__(self, kind: str, message: str, code: int) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code


def _emit_error(error: BridgeError) -> int:
    print(json.dumps({
        "ok": False,
        "bridge": "stage2-netns-test",
        "error": error.kind,
        "message": str(error),
    }, sort_keys=True), file=sys.stderr)
    return error.code


def parse_namespace(argv: Sequence[str]) -> str:
    if len(argv) != 1:
        raise BridgeError("usage", "Exactly one stage-2 client namespace name is required.", EXIT_USAGE)
    namespace = argv[0]
    if NAMESPACE_PATTERN.fullmatch(namespace) is None:
        raise BridgeError("validation", "Namespace name is outside the fixed stage-2 test scope.", EXIT_USAGE)
    return namespace


def _verify_root_owned_file(path: Path, expected_mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BridgeError("installation", f"Could not inspect {path}: {exc}", EXIT_SAFETY) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise BridgeError("installation", f"Expected a regular file: {path}", EXIT_SAFETY)
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise BridgeError("installation", f"File is not owned by root:root: {path}", EXIT_SAFETY)
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise BridgeError("installation", f"File mode is not {expected_mode:04o}: {path}", EXIT_SAFETY)
    if metadata.st_nlink != 1:
        raise BridgeError("installation", f"File has multiple hard links: {path}", EXIT_SAFETY)


def verify_execution_boundary(
    launcher_path: Path,
    namespace: str,
    environment: Mapping[str, str] | None = None,
) -> int:
    if os.geteuid() != 0:
        raise BridgeError("privilege", "The test bridge must run through pkexec.", EXIT_PRIVILEGE)
    env = os.environ if environment is None else environment
    raw_uid = env.get("PKEXEC_UID")
    if raw_uid is None or not raw_uid.isascii() or not raw_uid.isdecimal():
        raise BridgeError("privilege", "PKEXEC_UID is missing or invalid.", EXIT_PRIVILEGE)
    invoking_uid = int(raw_uid, 10)
    if invoking_uid <= 0:
        raise BridgeError("privilege", "The pkexec caller must be non-root.", EXIT_PRIVILEGE)

    try:
        actual_bridge = launcher_path.resolve(strict=True)
        expected_bridge = BRIDGE_PATH.resolve(strict=True)
        helper = HELPER_PATH.resolve(strict=True)
        ip_binary = IP_PATH.resolve(strict=True)
    except OSError as exc:
        raise BridgeError("installation", f"Could not resolve fixed path: {exc}", EXIT_SAFETY) from exc
    if actual_bridge != expected_bridge:
        raise BridgeError("installation", "Bridge is not running from its fixed path.", EXIT_SAFETY)
    _verify_root_owned_file(expected_bridge, 0o755)
    _verify_root_owned_file(helper, 0o755)
    _verify_root_owned_file(ip_binary, 0o755)

    namespace_path = NETNS_ROOT / namespace
    try:
        namespace_metadata = namespace_path.lstat()
    except OSError as exc:
        raise BridgeError("namespace", f"Could not inspect test namespace: {exc}", EXIT_SAFETY) from exc
    if stat.S_ISLNK(namespace_metadata.st_mode):
        raise BridgeError("namespace", "Test namespace path must not be a symbolic link.", EXIT_SAFETY)
    if namespace_metadata.st_uid != 0 or namespace_metadata.st_gid != 0:
        raise BridgeError("namespace", "Test namespace is not owned by root:root.", EXIT_SAFETY)
    if stat.S_IMODE(namespace_metadata.st_mode) & 0o022:
        raise BridgeError("namespace", "Test namespace is group- or world-writable.", EXIT_SAFETY)
    return invoking_uid


def sanitized_environment(invoking_uid: int) -> dict[str, str]:
    return {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C",
        "PKEXEC_UID": str(invoking_uid),
    }


def build_exec_argv(namespace: str) -> list[str]:
    return [
        str(IP_PATH), "netns", "exec", namespace,
        str(HELPER_PATH), *FIXED_HELPER_ARGUMENTS,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        namespace = parse_namespace(arguments)
        invoking_uid = verify_execution_boundary(Path(sys.argv[0]), namespace)
        os.execve(str(IP_PATH), build_exec_argv(namespace), sanitized_environment(invoking_uid))
    except BridgeError as exc:
        return _emit_error(exc)
    except OSError as exc:
        return _emit_error(BridgeError("execution", f"Could not enter test namespace: {exc}", EXIT_SAFETY))
    return EXIT_SAFETY


if __name__ == "__main__":
    raise SystemExit(main())
