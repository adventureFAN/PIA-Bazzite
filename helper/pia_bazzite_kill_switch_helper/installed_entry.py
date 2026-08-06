from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping, Sequence

from .cli import EXIT_PRIVILEGE, EXIT_SAFETY, main as helper_main
from .core import HELPER_STAGE
from .protocol import error_payload, infer_action

INSTALL_ROOT = Path("/usr/local/libexec/pia-bazzite")
INSTALLED_LAUNCHER = INSTALL_ROOT / "pia-bazzite-kill-switch-helper"
INSTALLED_SESSION_LAUNCHER = INSTALL_ROOT / "pia-bazzite-kill-switch-session"
INSTALLED_PACKAGE = INSTALL_ROOT / "pia_bazzite_kill_switch_helper"
MANIFEST = INSTALL_ROOT / "kill-switch-helper-manifest.json"
INSTALL_FORMAT = 1

EXPECTED_FILES: Mapping[str, int] = {
    "pia-bazzite-kill-switch-helper": 0o755,
    "pia-bazzite-kill-switch-session": 0o755,
    "pia_bazzite_kill_switch_helper/__init__.py": 0o644,
    "pia_bazzite_kill_switch_helper/cli.py": 0o644,
    "pia_bazzite_kill_switch_helper/core.py": 0o644,
    "pia_bazzite_kill_switch_helper/runner.py": 0o644,
    "pia_bazzite_kill_switch_helper/protocol.py": 0o644,
    "pia_bazzite_kill_switch_helper/installed_entry.py": 0o644,
    "pia_bazzite_kill_switch_helper/session_entry.py": 0o644,
}


class InstallationBoundaryError(RuntimeError):
    """Raised when the installed helper boundary cannot be proven safe."""


class AuthorizationBoundaryError(RuntimeError):
    """Raised when execution did not originate from a non-root pkexec caller."""


def _emit_error(action: str | None, kind: str, message: str, code: int) -> int:
    print(
        json.dumps(
            error_payload(
                action=action,
                helper_stage=HELPER_STAGE,
                kind=kind,
                message=message,
            ),
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return code


def _mode_bits(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _verify_safe_directory(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise InstallationBoundaryError(f"Could not inspect directory {path}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise InstallationBoundaryError(f"Expected a directory: {path}")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise InstallationBoundaryError(f"Directory is not owned by root:root: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise InstallationBoundaryError(f"Directory is group- or world-writable: {path}")


def _verify_safe_file(path: Path, expected_mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise InstallationBoundaryError(f"Could not inspect installed file {path}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallationBoundaryError(f"Installed path is not a regular file: {path}")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise InstallationBoundaryError(f"Installed file is not owned by root:root: {path}")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise InstallationBoundaryError(
            f"Installed file has mode {_mode_bits(path):04o}, expected {expected_mode:04o}: {path}"
        )
    if metadata.st_nlink != 1:
        raise InstallationBoundaryError(f"Installed file must have exactly one hard link: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    _verify_safe_file(path, 0o644)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallationBoundaryError(f"Could not read helper manifest safely: {exc}") from exc
    if not isinstance(document, dict):
        raise InstallationBoundaryError("Helper manifest is not a JSON object.")
    return document


def verify_installation(
    launcher_path: Path,
    *,
    install_root: Path = INSTALL_ROOT,
    installed_launcher: Path = INSTALLED_LAUNCHER,
    manifest_path: Path = MANIFEST,
) -> dict[str, str]:
    try:
        expected_launcher = installed_launcher.resolve(strict=True)
        actual_launcher = launcher_path.resolve(strict=True)
    except OSError as exc:
        raise InstallationBoundaryError(f"Could not resolve installed helper path: {exc}") from exc

    if actual_launcher != expected_launcher:
        raise InstallationBoundaryError(
            f"Helper must run from the fixed installed path {installed_launcher}."
        )

    resolved_root = install_root.resolve(strict=True)
    resolved_package = (install_root / "pia_bazzite_kill_switch_helper").resolve(strict=True)
    _verify_safe_directory(resolved_root.parent)
    _verify_safe_directory(resolved_root)
    _verify_safe_directory(resolved_package)

    try:
        resolved_manifest = manifest_path.resolve(strict=True)
    except OSError as exc:
        raise InstallationBoundaryError(f"Could not resolve helper manifest path: {exc}") from exc
    if resolved_manifest != resolved_root / manifest_path.name:
        raise InstallationBoundaryError("Helper manifest escaped the fixed helper directory.")
    manifest = _load_manifest(manifest_path)
    required_keys = {"schema_version", "install_format", "helper_stage", "protocol_version", "files"}
    if set(manifest) != required_keys:
        raise InstallationBoundaryError("Helper manifest shape is incomplete or unexpected.")
    if manifest.get("schema_version") != 1:
        raise InstallationBoundaryError("Unsupported helper manifest schema version.")
    if manifest.get("install_format") != INSTALL_FORMAT:
        raise InstallationBoundaryError("Unsupported helper installation format.")
    if manifest.get("helper_stage") != HELPER_STAGE:
        raise InstallationBoundaryError("Installed helper stage does not match this package.")
    from .protocol import PROTOCOL_VERSION
    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        raise InstallationBoundaryError("Installed helper protocol version does not match this package.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(EXPECTED_FILES):
        raise InstallationBoundaryError("Helper manifest file list is incomplete or unexpected.")

    verified_hashes: dict[str, str] = {}
    for relative_name, expected_mode in EXPECTED_FILES.items():
        candidate = (install_root / relative_name).resolve(strict=True)
        expected_candidate = resolved_root / relative_name
        if candidate != expected_candidate:
            raise InstallationBoundaryError(f"Installed file escaped the fixed helper directory: {relative_name}")
        _verify_safe_file(candidate, expected_mode)
        manifest_hash = files.get(relative_name)
        if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
            raise InstallationBoundaryError(f"Invalid manifest checksum for {relative_name}.")
        actual_hash = _sha256(candidate)
        if actual_hash != manifest_hash:
            raise InstallationBoundaryError(f"Installed helper checksum mismatch: {relative_name}")
        verified_hashes[relative_name] = actual_hash

    return verified_hashes


def verify_pkexec_authorization(environment: Mapping[str, str] | None = None) -> int:
    if os.geteuid() != 0:
        raise AuthorizationBoundaryError("Installed helper actions require root privileges via pkexec.")
    env = os.environ if environment is None else environment
    raw_uid = env.get("PKEXEC_UID")
    if raw_uid is None or not raw_uid.isascii() or not raw_uid.isdecimal():
        raise AuthorizationBoundaryError("PKEXEC_UID is missing or invalid; direct sudo/root execution is refused.")
    invoking_uid = int(raw_uid, 10)
    if invoking_uid <= 0:
        raise AuthorizationBoundaryError("The pkexec caller must be a non-root user.")
    return invoking_uid


def sanitize_environment(invoking_uid: int) -> None:
    os.environ.clear()
    os.environ.update(
        {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "PKEXEC_UID": str(invoking_uid),
        }
    )


def main(argv: Sequence[str] | None = None, *, launcher_path: Path | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    action = infer_action(raw_argv).action
    actual_launcher = Path(sys.argv[0]) if launcher_path is None else launcher_path
    try:
        verify_installation(actual_launcher)
        invoking_uid = verify_pkexec_authorization()
        sanitize_environment(invoking_uid)
        return helper_main(raw_argv, trusted_host=True)
    except AuthorizationBoundaryError as exc:
        return _emit_error(action, "privilege", str(exc), EXIT_PRIVILEGE)
    except InstallationBoundaryError as exc:
        return _emit_error(action, "installation-boundary", str(exc), EXIT_SAFETY)


__all__ = [
    "AuthorizationBoundaryError",
    "EXPECTED_FILES",
    "INSTALL_ROOT",
    "INSTALLED_LAUNCHER",
    "INSTALLED_SESSION_LAUNCHER",
    "INSTALL_FORMAT",
    "InstallationBoundaryError",
    "MANIFEST",
    "main",
    "sanitize_environment",
    "verify_installation",
    "verify_pkexec_authorization",
]
