#!/usr/bin/python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import sys
import time


IPV4_TEST_ADDRESS = "1.1.1.1"
IPV6_TEST_ADDRESS = "2606:4700:4700::1111"
DNS_TEST_ADDRESS = IPV4_TEST_ADDRESS
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_RESULT_PREFIX = "pia-bazzite-stage6b-sentinel-"
_STOP_PREFIX = "pia-bazzite-stage6b-sentinel-stop-"


class SentinelError(RuntimeError):
    pass


def _safe_tmp_path(value: str, *, prefix: str) -> Path:
    path = Path(value)
    if path.parent != Path("/tmp") or not path.name.startswith(prefix):
        raise SentinelError("Sentinel paths must use the fixed Stage-6B /tmp prefix.")
    if path.name in {prefix, ".", ".."} or "/" in path.name:
        raise SentinelError("Unsafe sentinel path.")
    return path


def _normalize_interface(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise SentinelError("Unsafe physical interface name.")
    if not _INTERFACE_PATTERN.fullmatch(value) or value in {"lo", "piabazzite"}:
        raise SentinelError("Unsafe physical interface name.")
    return value


def _sudo_invoking_owner() -> tuple[int, int]:
    """Return the real desktop user recorded by the fixed sudo boundary.

    The sentinel runs as root so SO_BINDTODEVICE works.  Its atomically replaced
    result file must nevertheless remain owned by the invoking desktop user;
    otherwise a completed baseline result cannot be removed from sticky /tmp and
    can be mistaken for the first protected sample on the next run.
    """

    if os.geteuid() != 0:
        raise SentinelError("The leak sentinel must run as root through sudo.")
    uid_text = os.environ.get("SUDO_UID", "")
    gid_text = os.environ.get("SUDO_GID", "")
    if not uid_text.isascii() or not uid_text.isdecimal():
        raise SentinelError("sudo did not provide a safe invoking user ID.")
    if not gid_text.isascii() or not gid_text.isdecimal():
        raise SentinelError("sudo did not provide a safe invoking group ID.")
    uid = int(uid_text, 10)
    gid = int(gid_text, 10)
    if uid <= 0 or gid < 0:
        raise SentinelError("The leak sentinel refuses a root or invalid invoking user.")
    return uid, gid


def _bind_to_device(sock: socket.socket, interface: str) -> None:
    option = getattr(socket, "SO_BINDTODEVICE", 25)
    sock.setsockopt(socket.SOL_SOCKET, option, interface.encode("ascii") + b"\0")


def _tcp(interface: str, family: int, address: str, port: int, timeout: float) -> bool:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            _bind_to_device(sock, interface)
            sock.connect((address, port))
        return True
    except OSError:
        return False


def _dns_udp(interface: str, timeout: float) -> bool:
    query = bytes.fromhex(
        "504901000001000000000000"
        "076578616d706c6503636f6d00"
        "00010001"
    )
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            _bind_to_device(sock, interface)
            sock.sendto(query, (DNS_TEST_ADDRESS, 53))
            response, source = sock.recvfrom(4096)
    except OSError:
        return False
    return (
        source[0] == DNS_TEST_ADDRESS
        and source[1] == 53
        and len(response) >= 12
        and response[:2] == query[:2]
    )


def _probe_once(
    interface: str,
    *,
    check_ipv6: bool,
    check_dns_tcp: bool,
    check_dns_udp: bool,
    timeout: float,
) -> dict[str, bool]:
    result = {
        "ipv4_tcp": _tcp(interface, socket.AF_INET, IPV4_TEST_ADDRESS, 443, timeout),
    }
    if check_ipv6:
        result["ipv6_tcp"] = _tcp(
            interface,
            socket.AF_INET6,
            IPV6_TEST_ADDRESS,
            443,
            timeout,
        )
    if check_dns_tcp:
        result["dns_tcp"] = _tcp(
            interface,
            socket.AF_INET,
            DNS_TEST_ADDRESS,
            53,
            timeout,
        )
    if check_dns_udp:
        result["dns_udp"] = _dns_udp(interface, timeout)
    return result


def _write_result(
    path: Path,
    payload: dict[str, object],
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    temporary = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        # Chown the temporary inode before the atomic replace.  Every published
        # result is therefore removable by the non-root parent in sticky /tmp.
        os.fchown(descriptor, owner_uid, owner_gid)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> int:
    interface = _normalize_interface(args.interface)
    result_path = _safe_tmp_path(args.result, prefix=_RESULT_PREFIX)
    stop_path = _safe_tmp_path(args.stop_file, prefix=_STOP_PREFIX)
    owner_uid, owner_gid = _sudo_invoking_owner()
    if args.max_seconds < 5 or args.max_seconds > 600:
        raise SentinelError("Sentinel duration must be between 5 and 600 seconds.")
    if args.interval < 0.05 or args.interval > 5.0:
        raise SentinelError("Sentinel interval is outside the allowed range.")
    if args.timeout < 0.05 or args.timeout > 2.0:
        raise SentinelError("Sentinel socket timeout is outside the allowed range.")

    started = time.monotonic()
    iterations = 0
    attempts: dict[str, int] = {}
    successes: dict[str, int] = {}
    last_success_monotonic: float | None = None

    while True:
        checks = _probe_once(
            interface,
            check_ipv6=args.check_ipv6,
            check_dns_tcp=args.check_dns_tcp,
            check_dns_udp=args.check_dns_udp,
            timeout=args.timeout,
        )
        iterations += 1
        for name, reachable in checks.items():
            attempts[name] = attempts.get(name, 0) + 1
            if reachable:
                successes[name] = successes.get(name, 0) + 1
                last_success_monotonic = time.monotonic()
            else:
                successes.setdefault(name, 0)

        elapsed = time.monotonic() - started
        payload: dict[str, object] = {
            "schema_version": 1,
            "interface": interface,
            "iterations": iterations,
            "attempts": attempts,
            "successes": successes,
            "leak_detected": any(value > 0 for value in successes.values()),
            "elapsed_seconds": round(elapsed, 3),
            "stopped": stop_path.exists(),
            "timed_out": elapsed >= args.max_seconds,
            "last_success_seconds": (
                None
                if last_success_monotonic is None
                else round(last_success_monotonic - started, 3)
            ),
        }
        _write_result(
            result_path,
            payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )

        if args.baseline_only:
            return 0 if bool(checks.get("ipv4_tcp")) else 2
        if stop_path.exists() or elapsed >= args.max_seconds:
            return 3 if payload["leak_detected"] else 0
        time.sleep(args.interval)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Root-bound fixed-target Stage-6B direct-path leak sentinel."
    )
    parser.add_argument("--interface", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--check-ipv6", action="store_true")
    parser.add_argument("--check-dns-tcp", action="store_true")
    parser.add_argument("--check-dns-udp", action="store_true")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=240.0)
    parser.add_argument("--interval", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=0.12)
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
