from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
from typing import Iterator, Sequence

from .core import (
    HELPER_STAGE,
    IPV6_GUARD_TABLE_NAME,
    TABLE_NAME,
    ValidationError,
    disabled_status,
    ipv6_guard_disabled_status,
    parse_endpoint,
    parse_ipv6_guard_status_json,
    parse_status_json,
    render_add_endpoint,
    render_disable_ruleset,
    render_ipv6_guard_disable_ruleset,
    render_ipv6_guard_enable_ruleset,
    render_enable_ruleset,
    render_remove_endpoint,
    render_set_endpoints,
    render_set_interfaces,
)
from .protocol import error_payload, infer_action, success_payload
from .runner import NftError, NftRunner

LOCK_PATH = Path("/run/lock/pia-bazzite-kill-switch-helper.lock")
EXIT_VALIDATION = 2
EXIT_PRIVILEGE = 3
EXIT_NFT = 4
EXIT_VERIFY = 5
EXIT_SAFETY = 6


class SafetyBoundaryError(RuntimeError):
    pass


class JsonArgumentError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise JsonArgumentError(message)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="pia-bazzite-kill-switch-helper",
        description=(
            "Restricted PIA Bazzite kill-switch helper. It can manage only the "
            f"fixed nftables table {TABLE_NAME!r}."
        ),
    )
    parser.add_argument("--version", action="version", version=f"stage {HELPER_STAGE}")
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("status", help="Read and verify the fixed production table.")

    enable = subparsers.add_parser("enable", help="Atomically replace the fixed table.")
    enable.add_argument("--interface", action="append", required=True, dest="interfaces")
    enable.add_argument("--endpoint", action="append", required=True, dest="endpoints")

    set_interfaces = subparsers.add_parser(
        "set-interfaces",
        help="Atomically replace the allowed physical-interface set.",
    )
    set_interfaces.add_argument(
        "--interface", action="append", required=True, dest="interfaces"
    )

    set_endpoints = subparsers.add_parser(
        "set-endpoints",
        help="Atomically replace both exact WireGuard endpoint sets.",
    )
    set_endpoints.add_argument(
        "--endpoint", action="append", required=True, dest="endpoints"
    )

    add_endpoint = subparsers.add_parser("add-endpoint", help="Add one exact UDP endpoint.")
    add_endpoint.add_argument("--endpoint", required=True)

    remove_endpoint = subparsers.add_parser(
        "remove-endpoint", help="Idempotently remove one exact UDP endpoint."
    )
    remove_endpoint.add_argument("--endpoint", required=True)

    subparsers.add_parser("disable", help="Idempotently remove only the fixed production table.")
    subparsers.add_parser(
        "emergency-reset",
        help="Idempotently remove only the fixed candidate table (explicit recovery action).",
    )
    subparsers.add_parser(
        "ipv6-guard-status",
        help="Read and verify the fixed IPv6-only guard table.",
    )
    subparsers.add_parser(
        "ipv6-guard-enable",
        help="Atomically replace the fixed IPv6-only guard table.",
    )
    subparsers.add_parser(
        "ipv6-guard-disable",
        help="Idempotently remove only the fixed IPv6-only guard table.",
    )
    return parser


def _emit(payload: dict[str, object], *, stream: object = sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True), file=stream)


def _error(action: str | None, kind: str, message: str, code: int) -> int:
    _emit(
        error_payload(
            action=action,
            helper_stage=HELPER_STAGE,
            kind=kind,
            message=message,
        ),
        stream=sys.stderr,
    )
    return code


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError(
            "Kill-switch helper actions require root privileges."
        )


def _require_isolated_network_namespace() -> None:
    try:
        current_namespace = os.stat("/proc/self/ns/net").st_ino
        initial_namespace = os.stat("/proc/1/ns/net").st_ino
    except OSError as exc:
        raise SafetyBoundaryError(
            f"Could not verify the network namespace safety boundary: {exc}"
        ) from exc
    if current_namespace == initial_namespace:
        raise SafetyBoundaryError(
            "The project helper refuses the host network namespace. "
            "Host operation is allowed only through the verified installed launcher."
        )


@contextmanager
def _exclusive_lock() -> Iterator[None]:
    LOCK_PATH.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(LOCK_PATH, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1:
            raise OSError("Unsafe helper lock file ownership or type.")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _status(runner: NftRunner, *, action: str) -> tuple[dict[str, object], int]:
    if not runner.table_exists():
        status = disabled_status()
        return success_payload(action=action, helper_stage=HELPER_STAGE, fields=status), 0

    result = runner.list_table_json()
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "could not read candidate table").strip()
        raise NftError(detail)
    status = parse_status_json(result.stdout)
    if status["verified"]:
        return success_payload(action=action, helper_stage=HELPER_STAGE, fields=status), 0
    payload = success_payload(action=action, helper_stage=HELPER_STAGE, fields=status)
    payload["ok"] = False
    payload["error"] = "verification"
    payload["message"] = "The helper table exists but failed structural verification."
    return payload, EXIT_VERIFY


def _ipv6_guard_status(
    runner: NftRunner,
    *,
    action: str,
) -> tuple[dict[str, object], int]:
    if not runner.table_exists(IPV6_GUARD_TABLE_NAME):
        status = ipv6_guard_disabled_status()
        return success_payload(action=action, helper_stage=HELPER_STAGE, fields=status), 0

    result = runner.list_table_json(IPV6_GUARD_TABLE_NAME)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "could not read IPv6 guard table").strip()
        raise NftError(detail)
    status = parse_ipv6_guard_status_json(result.stdout)
    if status["verified"]:
        return success_payload(action=action, helper_stage=HELPER_STAGE, fields=status), 0
    payload = success_payload(action=action, helper_stage=HELPER_STAGE, fields=status)
    payload["ok"] = False
    payload["error"] = "verification"
    payload["message"] = "The IPv6 guard table exists but failed structural verification."
    return payload, EXIT_VERIFY


def main(
    argv: Sequence[str] | None = None,
    *,
    trusted_host: bool = False,
) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    request_context = infer_action(raw_argv)
    action: str | None = request_context.action
    try:
        args = _parser().parse_args(raw_argv)
        action = args.action

        # Render and validate every untrusted input before touching the root-owned
        # lock or invoking nftables.
        script: str | None = None
        if args.action == "enable":
            script = render_enable_ruleset(args.interfaces, args.endpoints)
        elif args.action == "set-interfaces":
            script = render_set_interfaces(args.interfaces)
        elif args.action == "set-endpoints":
            script = render_set_endpoints(args.endpoints)
        elif args.action == "add-endpoint":
            script = render_add_endpoint(parse_endpoint(args.endpoint))
        elif args.action == "remove-endpoint":
            script = render_remove_endpoint(parse_endpoint(args.endpoint))
        elif args.action in {"disable", "emergency-reset"}:
            script = render_disable_ruleset()
        elif args.action == "ipv6-guard-enable":
            script = render_ipv6_guard_enable_ruleset()
        elif args.action == "ipv6-guard-disable":
            script = render_ipv6_guard_disable_ruleset()
        elif args.action not in {"status", "ipv6-guard-status"}:  # pragma: no cover
            raise ValidationError(f"Unsupported action: {args.action}")

        _require_root()
        if not trusted_host:
            _require_isolated_network_namespace()
        runner = NftRunner()

        if args.action == "status":
            payload, code = _status(runner, action=args.action)
            _emit(payload, stream=sys.stdout if code == 0 else sys.stderr)
            return code
        if args.action == "ipv6-guard-status":
            payload, code = _ipv6_guard_status(runner, action=args.action)
            _emit(payload, stream=sys.stdout if code == 0 else sys.stderr)
            return code

        assert script is not None
        with _exclusive_lock():
            # The normal-mode IPv6 guard and the full Session Kill Switch are
            # deliberately separate protection modes.  Refuse to arm either
            # one while the other table exists; this keeps even concurrent
            # authenticated sessions from creating an ambiguous combined state.
            if args.action == "ipv6-guard-enable" and runner.table_exists(TABLE_NAME):
                raise SafetyBoundaryError(
                    "Refusing to enable the IPv6-only guard while the full Session Kill Switch table exists."
                )
            if args.action == "enable" and runner.table_exists(IPV6_GUARD_TABLE_NAME):
                raise SafetyBoundaryError(
                    "Refusing to enable the full Session Kill Switch while the IPv6-only guard table exists."
                )
            runner.check_script(script)
            runner.apply_script(script)
            if args.action.startswith("ipv6-guard-"):
                payload, code = _ipv6_guard_status(runner, action=args.action)
            else:
                payload, code = _status(runner, action=args.action)
            _emit(payload, stream=sys.stdout if code == 0 else sys.stderr)
            return code

    except (JsonArgumentError, ValidationError) as exc:
        return _error(action, "validation", str(exc), EXIT_VALIDATION)
    except PermissionError as exc:
        return _error(action, "privilege", str(exc), EXIT_PRIVILEGE)
    except SafetyBoundaryError as exc:
        return _error(action, "safety-boundary", str(exc), EXIT_SAFETY)
    except NftError as exc:
        return _error(action, "nftables", str(exc), EXIT_NFT)
    except OSError as exc:
        return _error(action, "operating-system", str(exc), EXIT_NFT)


if __name__ == "__main__":
    raise SystemExit(main())
