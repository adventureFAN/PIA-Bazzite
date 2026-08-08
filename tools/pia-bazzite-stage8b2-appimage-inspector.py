#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pia_bazzite import __version__
from pia_bazzite.helper_installation import (
    BUNDLE_MANIFEST_NAME,
    BUNDLE_SOURCE_MODES,
    HelperInstallationState,
    PackagedHelperManager,
)
from pia_bazzite.kill_switch_client import EXPECTED_HELPER_STAGE, EXPECTED_PROTOCOL_VERSION


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_bundle(bundle: Path) -> dict[str, object]:
    root_meta = bundle.lstat()
    root = bundle.resolve(strict=True)
    if bundle.is_symlink() or not stat.S_ISDIR(root_meta.st_mode):
        raise RuntimeError("bundle is not a real directory")
    manifest_path = root / BUNDLE_MANIFEST_NAME
    manifest_meta = manifest_path.lstat()
    if manifest_path.is_symlink() or not stat.S_ISREG(manifest_meta.st_mode) or manifest_meta.st_nlink != 1:
        raise RuntimeError("bundle manifest is not a safe regular file")
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"schema_version", "app_version", "helper_stage", "protocol_version", "files"}
    if not isinstance(document, dict) or set(document) != required:
        raise RuntimeError("bundle manifest shape is invalid")
    if document["schema_version"] != 1:
        raise RuntimeError("bundle schema version is invalid")
    if document["app_version"] != __version__:
        raise RuntimeError("bundle app version does not match runtime")
    if document["helper_stage"] != EXPECTED_HELPER_STAGE:
        raise RuntimeError("bundle helper stage does not match runtime")
    if document["protocol_version"] != EXPECTED_PROTOCOL_VERSION:
        raise RuntimeError("bundle protocol version does not match runtime")
    files = document["files"]
    if not isinstance(files, dict) or set(files) != set(BUNDLE_SOURCE_MODES):
        raise RuntimeError("bundle file map is incomplete or unexpected")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if not path.is_dir()
    }
    if actual != set(BUNDLE_SOURCE_MODES) | {BUNDLE_MANIFEST_NAME}:
        raise RuntimeError("bundle contains missing or extra files")
    for relative, expected_mode in BUNDLE_SOURCE_MODES.items():
        path = root / relative
        meta = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
            raise RuntimeError(f"unsafe bundle file: {relative}")
        if stat.S_IMODE(meta.st_mode) != expected_mode:
            raise RuntimeError(f"wrong bundle mode: {relative}")
        if sha256(path) != files[relative]:
            raise RuntimeError(f"bundle checksum mismatch: {relative}")
    return document


def audit_installed(bundle: Path) -> dict[str, object]:
    audit = PackagedHelperManager(bundle_path=bundle).audit()
    return {
        "state": audit.state.value,
        "packaged": audit.packaged,
        "current": audit.current,
        "installable": audit.installable,
        "details": audit.details,
    }


def snapshot_installed(bundle: Path) -> dict[str, object]:
    manager = PackagedHelperManager(bundle_path=bundle)
    audit = manager.audit()
    if audit.state is not HelperInstallationState.CURRENT:
        raise RuntimeError(f"installed helper is not current: {audit.state.value}: {audit.details}")
    paths = sorted(manager.install_root.rglob("*"))
    result: dict[str, object] = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        meta = path.lstat()
        result[path.relative_to(manager.install_root).as_posix()] = {
            "sha256": sha256(path),
            "inode": meta.st_ino,
            "size": meta.st_size,
            "mtime_ns": meta.st_mtime_ns,
            "uid": meta.st_uid,
            "gid": meta.st_gid,
            "mode": stat.S_IMODE(meta.st_mode),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("bundle", "audit-installed", "snapshot-installed"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--expect-state", choices=[state.value for state in HelperInstallationState])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.action == "bundle":
            payload = inspect_bundle(args.bundle)
        elif args.action == "audit-installed":
            inspect_bundle(args.bundle)
            payload = audit_installed(args.bundle)
            if args.expect_state and payload["state"] != args.expect_state:
                raise RuntimeError(
                    f"installed helper state is {payload['state']}, expected {args.expect_state}: {payload['details']}"
                )
        else:
            inspect_bundle(args.bundle)
            payload = snapshot_installed(args.bundle)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
