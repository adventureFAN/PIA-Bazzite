#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

HELPER_STAGE = 5
PROTOCOL_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1

BUNDLE_FILES: tuple[tuple[str, int], ...] = (
    ("tools/pia-bazzite-stage2-helper-installer.sh", 0o755),
    ("helper/pia-bazzite-kill-switch-helper-installed", 0o755),
    ("helper/pia-bazzite-kill-switch-session-installed", 0o755),
    ("helper/pia_bazzite_kill_switch_helper/__init__.py", 0o644),
    ("helper/pia_bazzite_kill_switch_helper/cli.py", 0o644),
    ("helper/pia_bazzite_kill_switch_helper/core.py", 0o644),
    ("helper/pia_bazzite_kill_switch_helper/runner.py", 0o644),
    ("helper/pia_bazzite_kill_switch_helper/protocol.py", 0o644),
    ("helper/pia_bazzite_kill_switch_helper/installed_entry.py", 0o644),
    ("helper/pia_bazzite_kill_switch_helper/session_entry.py", 0o644),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_bundle(*, root: Path, destination: Path, version: str) -> Path:
    root = root.resolve(strict=True)
    if not version or any(ch.isspace() for ch in version):
        raise ValueError("Application version must be a non-empty token.")

    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise RuntimeError(f"Refusing unsafe helper bundle destination: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o755)

    hashes: dict[str, str] = {}
    for relative, mode in BUNDLE_FILES:
        source = root / relative
        metadata = source.lstat()
        if source.is_symlink() or not source.is_file() or metadata.st_nlink != 1:
            raise RuntimeError(f"Unsafe helper bundle source: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(mode)
        hashes[relative] = _sha256(target)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "app_version": version,
        "helper_stage": HELPER_STAGE,
        "protocol_version": PROTOCOL_VERSION,
        "files": hashes,
    }
    manifest_path = destination / "bundle-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o644)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    manifest = build_bundle(root=args.root, destination=args.destination, version=args.version)
    print(f"Built Kill Switch helper bundle: {manifest.parent}")
    print(f"Bundle manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
