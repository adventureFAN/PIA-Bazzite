#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
from importlib import metadata
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Callable, Iterable

RUNTIME_ROOTS = (
    "PySide6-Essentials",
    "keyring",
    "SecretStorage",
    "requests",
)

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)")
_LICENSE_PREFIXES = ("license", "copying", "notice", "authors")


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def requirement_name(value: str) -> str | None:
    match = _NAME_RE.match(value)
    return match.group(1) if match else None


def is_license_path(value: object) -> bool:
    path = PurePosixPath(str(value).replace("\\", "/"))
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    return "licenses" in parts or name.startswith(_LICENSE_PREFIXES)


def _safe_relative_path(value: object) -> Path | None:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return None
    return Path(*path.parts)


def collect_runtime_licenses(
    destination: Path,
    roots: Iterable[str] = RUNTIME_ROOTS,
    distribution_getter: Callable[[str], object] = metadata.distribution,
) -> list[tuple[str, str, list[str]]]:
    destination = destination.resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o755)

    queue: deque[tuple[str, bool]] = deque((name, True) for name in roots)
    seen: set[str] = set()
    components: list[tuple[str, str, list[str]]] = []

    while queue:
        requested, required_root = queue.popleft()
        key = normalize_name(requested)
        if key in seen:
            continue
        seen.add(key)

        try:
            dist = distribution_getter(requested)
        except metadata.PackageNotFoundError:
            if required_root:
                raise RuntimeError(f"Required runtime distribution is not installed: {requested}")
            continue

        dist_metadata = dist.metadata
        name = str(dist_metadata.get("Name") or requested)
        version = str(dist_metadata.get("Version") or getattr(dist, "version", "unknown"))

        for requirement in getattr(dist, "requires", None) or ():
            child = requirement_name(str(requirement))
            if child:
                queue.append((child, False))

        component_dir = destination / re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        copied: list[str] = []
        for dist_file in getattr(dist, "files", None) or ():
            if not is_license_path(dist_file):
                continue
            relative = _safe_relative_path(dist_file)
            if relative is None:
                continue
            source = Path(dist.locate_file(dist_file))
            if not source.is_file():
                continue
            target = component_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
            copied.append(str(target.relative_to(destination)))

        license_expression = str(dist_metadata.get("License-Expression") or "").strip()
        license_text = str(dist_metadata.get("License") or "").strip()
        license_value = license_expression or license_text or "not declared in package metadata"
        components.append((name, version, sorted(copied)))

        summary = component_dir / "PACKAGE_METADATA.txt"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(
            "\n".join(
                [
                    f"Name: {name}",
                    f"Version: {version}",
                    f"License metadata: {license_value}",
                    "License files copied: " + (str(len(copied)) if copied else "0"),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        summary.chmod(0o644)

    components.sort(key=lambda item: normalize_name(item[0]))
    lines = [
        "PIA Bazzite bundled Python runtime components",
        "",
        "This manifest is generated from the exact Python environment used for the AppImage build.",
        "License/copyright files are copied below when the installed distribution supplies them.",
        "The upstream package metadata remains authoritative for licensing terms.",
        "",
    ]
    for name, version, copied in components:
        lines.append(f"- {name} {version} (copied license files: {len(copied)})")
    lines.append("")
    (destination / "COMPONENTS.txt").write_text("\n".join(lines), encoding="utf-8")
    (destination / "COMPONENTS.txt").chmod(0o644)
    return components


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    components = collect_runtime_licenses(args.destination)
    print(f"Collected third-party metadata for {len(components)} bundled runtime distributions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
