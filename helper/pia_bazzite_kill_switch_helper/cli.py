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
    SCHEMA_VERSION,
    TABLE_NAME,
    ValidationError,
    disabled_status,
    parse_endpoint,
    parse_status_json,
    render_add_endpoint,
    render_disable_ruleset,
    render_enable_ruleset,
    render_remove_endpoint,
)
from .runner import NftError, NftRunner

LOCK_PATH = Path("/run/lock/pia-bazzite-kill-switch-helper-stage1.lock")
EXIT_VALIDATION = 2
EXIT_PRIVILEGE = 3
EXIT_NFT = 4
EXIT_VERIFY = 5
EXIT_SAFETY = 6


class SafetyBoundaryError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pia-bazzite-kill-switch-helper",
        description=(
            "Restricted stage-1 test helper. It can only manage the fixed "
            f"nftables table {TABLE_NAME!r}."
        ),
    )
    parser.add_argument("--version", action="version", version=f"stage {HELPER_STAGE}")
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("status", help="Read and verify the fixed test table.")

    enable = subparsers.add_parser("enable", help="Atomically replace the fixed test table.")
    enable.add_argument("--interface", action="append", required=True, dest="interfaces")
    enable.add_argument("--endpoint", action="append", required=True, dest="endpoints")

    add_endpoint = subparsers.add_parser("add-endpoint", help="Add one exact UDP endpoint.")
    add_endpoint.add_argument("--endpoint", required=True)

    remove_endpoint = subparsers.add_parser(
        "remove-endpoint", help="Idempotently remove one exact UDP endpoint."
    )
    remove_endpoint.add_argument("--endpoint", required=True)

    subparsers.add_parser("disable", help="Idempotently remove only the fixed test table.")
    subparsers.add_parser(
        "emergency-reset",
        help="Idempotently remove only the fixed test table (explicit recovery action).",
    )
    return parser


def _emit(payload: dict[str, object], *, stream: object = sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True), file=stream)


def _error(kind: str, message: str, code: int) -> int:
    _emit(
        {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "helper_stage": HELPER_STAGE,
            "error": kind,
            "message": message,
        },
        stream=sys.stderr,
    )
    return code


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Stage-1 helper actions require root privileges inside the test namespace.")


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
            "Stage-1 helper refuses the host network namespace. "
            "Run it only through the isolated namespace test."
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
            raise OSError("Unsafe stage-1 helper lock file ownership or type.")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        # The file is intentionally retained as a root-owned lock anchor.


def _status(runner: NftRunner) -> tuple[dict[str, object], int]:
    if not runner.table_exists():
        status = disabled_status()
        return {"ok": True, **status}, 0

    result = runner.list_table_json()
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "could not read test table").strip()
        raise NftError(detail)
    status = parse_status_json(result.stdout)
    return {"ok": bool(status["verified"]), **status}, 0 if status["verified"] else EXIT_VERIFY


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)

        # Validate and render all user-controlled input before touching the
        # privileged lock file or invoking nftables.  Apart from producing a
        # deterministic validation error, this keeps malformed requests free
        # of privileged side effects.
        script: str | None = None
        if args.action == "enable":
            script = render_enable_ruleset(args.interfaces, args.endpoints)
        elif args.action == "add-endpoint":
            script = render_add_endpoint(parse_endpoint(args.endpoint))
        elif args.action == "remove-endpoint":
            script = render_remove_endpoint(parse_endpoint(args.endpoint))
        elif args.action in {"disable", "emergency-reset"}:
            script = render_disable_ruleset()
        elif args.action != "status":  # pragma: no cover - argparse prevents this branch.
            raise ValidationError(f"Unsupported action: {args.action}")

        _require_root()
        _require_isolated_network_namespace()
        runner = NftRunner()

        if args.action == "status":
            payload, code = _status(runner)
            _emit(payload, stream=sys.stdout if code == 0 else sys.stderr)
            return code

        assert script is not None  # All mutating argparse actions render above.
        with _exclusive_lock():
            runner.check_script(script)
            runner.apply_script(script)

            payload, code = _status(runner)
            payload["action"] = args.action
            _emit(payload, stream=sys.stdout if code == 0 else sys.stderr)
            return code

    except ValidationError as exc:
        return _error("validation", str(exc), EXIT_VALIDATION)
    except PermissionError as exc:
        return _error("privilege", str(exc), EXIT_PRIVILEGE)
    except SafetyBoundaryError as exc:
        return _error("safety-boundary", str(exc), EXIT_SAFETY)
    except NftError as exc:
        return _error("nftables", str(exc), EXIT_NFT)
    except OSError as exc:
        return _error("operating-system", str(exc), EXIT_NFT)


if __name__ == "__main__":
    raise SystemExit(main())
