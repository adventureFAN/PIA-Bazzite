from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Mapping, Protocol, Sequence

from . import __version__
from .kill_switch_client import EXPECTED_HELPER_STAGE, EXPECTED_PROTOCOL_VERSION

BUNDLE_ENVIRONMENT_KEY = "PIA_BAZZITE_HELPER_BUNDLE"
BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
BUNDLE_SCHEMA_VERSION = 1
INSTALL_SCHEMA_VERSION = 1
INSTALL_FORMAT = 1
PKEXEC_PATH = Path("/usr/bin/pkexec")
BASH_PATH = Path("/usr/bin/bash")
PYTHON_PATH = Path("/usr/bin/python3")
INSTALL_ROOT = Path("/usr/local/libexec/pia-bazzite")
INSTALL_MANIFEST = INSTALL_ROOT / "kill-switch-helper-manifest.json"
MAX_INSTALLER_OUTPUT_BYTES = 128 * 1024

# The runtime keeps an independent copy of the packaging contract. Release tests
# require this to remain byte-for-byte aligned with build-helper-bundle.py.
BUNDLE_SOURCE_MODES: Mapping[str, int] = {
    "tools/pia-bazzite-stage2-helper-installer.sh": 0o755,
    "helper/pia-bazzite-kill-switch-helper-installed": 0o755,
    "helper/pia-bazzite-kill-switch-session-installed": 0o755,
    "helper/pia_bazzite_kill_switch_helper/__init__.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/cli.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/core.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/runner.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/protocol.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/installed_entry.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/session_entry.py": 0o644,
}

SOURCE_TO_INSTALLED: Mapping[str, str] = {
    "helper/pia-bazzite-kill-switch-helper-installed": "pia-bazzite-kill-switch-helper",
    "helper/pia-bazzite-kill-switch-session-installed": "pia-bazzite-kill-switch-session",
    "helper/pia_bazzite_kill_switch_helper/__init__.py": "pia_bazzite_kill_switch_helper/__init__.py",
    "helper/pia_bazzite_kill_switch_helper/cli.py": "pia_bazzite_kill_switch_helper/cli.py",
    "helper/pia_bazzite_kill_switch_helper/core.py": "pia_bazzite_kill_switch_helper/core.py",
    "helper/pia_bazzite_kill_switch_helper/runner.py": "pia_bazzite_kill_switch_helper/runner.py",
    "helper/pia_bazzite_kill_switch_helper/protocol.py": "pia_bazzite_kill_switch_helper/protocol.py",
    "helper/pia_bazzite_kill_switch_helper/installed_entry.py": "pia_bazzite_kill_switch_helper/installed_entry.py",
    "helper/pia_bazzite_kill_switch_helper/session_entry.py": "pia_bazzite_kill_switch_helper/session_entry.py",
}

INSTALLED_MODES: Mapping[str, int] = {
    SOURCE_TO_INSTALLED[source]: BUNDLE_SOURCE_MODES[source]
    for source in SOURCE_TO_INSTALLED
}


ROOT_STAGING_BOOTSTRAP = r"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

SOURCE_MODES = {
    "tools/pia-bazzite-stage2-helper-installer.sh": 0o755,
    "helper/pia-bazzite-kill-switch-helper-installed": 0o755,
    "helper/pia-bazzite-kill-switch-session-installed": 0o755,
    "helper/pia_bazzite_kill_switch_helper/__init__.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/cli.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/core.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/runner.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/protocol.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/installed_entry.py": 0o644,
    "helper/pia_bazzite_kill_switch_helper/session_entry.py": 0o644,
}
MANIFEST_NAME = "bundle-manifest.json"


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def read_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def require_directory_fd(fd: int, uid: int, label: str) -> None:
    metadata = os.fstat(fd)
    if not stat.S_ISDIR(metadata.st_mode):
        fail(f"{label} is not a directory")
    if metadata.st_uid != uid:
        fail(f"{label} has the wrong owner")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        fail(f"{label} must have mode 0700")


def read_user_file(root_fd: int, relative: str, uid: int, mode: int) -> bytes:
    parts = relative.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        fail(f"invalid helper path: {relative}")
    directory_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            require_directory_fd(directory_fd, uid, f"staging directory for {relative}")
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                fail(f"unsafe staged helper file: {relative}")
            if metadata.st_uid != uid or stat.S_IMODE(metadata.st_mode) != mode:
                fail(f"wrong owner or mode for staged helper file: {relative}")
            return read_fd(fd)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def write_root_file(root: Path, relative: str, data: bytes, mode: int) -> None:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = destination.parent
    while current != root:
        os.chmod(current, 0o700)
        current = current.parent
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    os.chown(destination, 0, 0)
    os.chmod(destination, mode)


def main() -> int:
    if os.geteuid() != 0:
        fail("privilege handoff must run as root")
    if len(sys.argv) != 4:
        fail("invalid privilege-handoff arguments")
    source_arg, expected_manifest_digest, expected_app_version = sys.argv[1:]
    caller_text = os.environ.get("PKEXEC_UID", "")
    if not caller_text.isascii() or not caller_text.isdecimal():
        fail("PKEXEC_UID is missing or invalid")
    caller_uid = int(caller_text)
    if caller_uid <= 0:
        fail("privilege handoff requires a non-root pkexec caller")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_digest):
        fail("trusted manifest digest is invalid")
    if not re.fullmatch(r"[0-9A-Za-z.+_-]{1,32}", expected_app_version):
        fail("expected app version is invalid")

    source = Path(source_arg)
    if source.parent != Path("/tmp") or not source.name.startswith("pia-bazzite-helper-install-"):
        fail("staged helper source is outside the fixed private /tmp namespace")

    root_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_staging: Path | None = None
    try:
        require_directory_fd(root_fd, caller_uid, "staged helper root")
        manifest_bytes = read_user_file(root_fd, MANIFEST_NAME, caller_uid, 0o644)
        if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_digest:
            fail("staged helper manifest no longer matches the trusted digest")
        try:
            document = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            fail("staged helper manifest is invalid JSON")
        required = {"schema_version", "app_version", "helper_stage", "protocol_version", "files"}
        if not isinstance(document, dict) or set(document) != required:
            fail("staged helper manifest shape is invalid")
        if document.get("schema_version") != 1:
            fail("staged helper manifest schema is unsupported")
        if document.get("app_version") != expected_app_version:
            fail("staged helper app version does not match the authorizing AppImage")
        if document.get("helper_stage") != 5 or document.get("protocol_version") != 1:
            fail("staged helper compatibility metadata is invalid")
        files = document.get("files")
        if not isinstance(files, dict) or set(files) != set(SOURCE_MODES):
            fail("staged helper file map is invalid")

        root_staging = Path(tempfile.mkdtemp(prefix="pia-bazzite-helper-root-", dir="/run"))
        os.chown(root_staging, 0, 0)
        os.chmod(root_staging, 0o700)
        write_root_file(root_staging, MANIFEST_NAME, manifest_bytes, 0o644)
        for relative, mode in SOURCE_MODES.items():
            data = read_user_file(root_fd, relative, caller_uid, mode)
            expected = files.get(relative)
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                fail(f"invalid manifest checksum for {relative}")
            if hashlib.sha256(data).hexdigest() != expected:
                fail(f"staged helper checksum mismatch: {relative}")
            write_root_file(root_staging, relative, data, mode)

        installer = root_staging / "tools/pia-bazzite-stage2-helper-installer.sh"
        completed = subprocess.run(
            ["/usr/bin/bash", str(installer), "install-packaged", expected_manifest_digest],
            stdin=subprocess.DEVNULL,
            check=False,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
        )
        return int(completed.returncode)
    finally:
        os.close(root_fd)
        if root_staging is not None:
            shutil.rmtree(root_staging, ignore_errors=True)


raise SystemExit(main())
"""


class HelperInstallationState(str, Enum):
    UNMANAGED_SOURCE = "unmanaged-source"
    CURRENT = "current"
    MISSING = "missing"
    OUTDATED = "outdated"
    UNSAFE = "unsafe"
    BUNDLE_INVALID = "bundle-invalid"


class HelperInstallationError(RuntimeError):
    """Base class for packaged helper installation/upgrade failures."""


class HelperBundleValidationError(HelperInstallationError):
    """Raised when the AppImage helper payload cannot be proven intact."""


class HelperInstallationUnsafeError(HelperInstallationError):
    """Raised when an installed target cannot be safely replaced."""


class HelperInstallationAuthorizationDenied(HelperInstallationError):
    """Raised when the administrator authorization is cancelled or denied."""


@dataclass(frozen=True, slots=True)
class HelperInstallationAudit:
    state: HelperInstallationState
    packaged: bool
    details: str = ""

    @property
    def current(self) -> bool:
        return self.state in {
            HelperInstallationState.UNMANAGED_SOURCE,
            HelperInstallationState.CURRENT,
        }

    @property
    def installable(self) -> bool:
        return self.state in {
            HelperInstallationState.MISSING,
            HelperInstallationState.OUTDATED,
        }


@dataclass(frozen=True, slots=True)
class InstallerResult:
    returncode: int
    stdout: str
    stderr: str


class InstallerRunner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> InstallerResult:
        ...


class SubprocessInstallerRunner:
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> InstallerResult:
        completed = subprocess.run(
            list(arguments),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=dict(environment),
        )
        return InstallerResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_environment(source: Mapping[str, str]) -> dict[str, str]:
    dangerous = {
        "APPDIR",
        "APPIMAGE",
        "ARGV0",
        BUNDLE_ENVIRONMENT_KEY,
        "GCONV_PATH",
        "GI_TYPELIB_PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "PKEXEC_UID",
        "QML2_IMPORT_PATH",
        "QT_PLUGIN_PATH",
    }
    environment: dict[str, str] = {}
    for key, value in source.items():
        if key in dangerous or key.startswith("LD_") or key.startswith("SUDO_"):
            continue
        environment[key] = value
    environment["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    return environment


def _verify_fixed_executable(
    path: Path,
    role: str,
    *,
    allow_safe_symlink: bool = False,
) -> None:
    if not path.is_absolute():
        raise HelperInstallationError(f"The fixed {role} path is not absolute: {path}")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise HelperInstallationError(f"The fixed {role} is unavailable: {path}") from exc

    inspected_path = path
    if stat.S_ISLNK(metadata.st_mode):
        if not allow_safe_symlink:
            raise HelperInstallationError(f"The fixed {role} is not a regular file: {path}")
        try:
            parent_meta = path.parent.lstat()
            resolved = path.resolve(strict=True)
            resolved_meta = resolved.lstat()
        except OSError as exc:
            raise HelperInstallationError(f"The fixed {role} symlink is unsafe: {path}") from exc
        parent_mode = stat.S_IMODE(parent_meta.st_mode)
        if (
            not stat.S_ISDIR(parent_meta.st_mode)
            or parent_meta.st_uid != 0
            or parent_meta.st_gid != 0
            or parent_mode & 0o022
        ):
            raise HelperInstallationError(
                f"The fixed {role} symlink parent is not root protected: {path.parent}"
            )
        # Fedora/Bazzite commonly exposes /usr/bin/python3 as a root-owned
        # symlink to the versioned interpreter in the same root-protected
        # directory.  Permit only that narrow system layout.
        if resolved.parent != path.parent:
            raise HelperInstallationError(
                f"The fixed {role} symlink leaves its root-protected directory: {path}"
            )
        metadata = resolved_meta
        inspected_path = resolved

    if not stat.S_ISREG(metadata.st_mode):
        raise HelperInstallationError(f"The fixed {role} is not a regular file: {inspected_path}")
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise HelperInstallationError(
            f"The fixed {role} is not owned by root:root: {inspected_path}"
        )
    if metadata.st_nlink != 1 or mode & 0o022 or not (mode & 0o111):
        raise HelperInstallationError(
            f"The fixed {role} has unsafe permissions: {inspected_path}"
        )


class PackagedHelperManager:
    """Verify and explicitly install the helper payload carried by the AppImage.

    Source-tree runs intentionally remain unmanaged.  Release AppImages set one
    fixed environment variable in AppRun, which turns this gate on before any
    privileged Kill Switch helper is trusted.
    """

    def __init__(
        self,
        *,
        bundle_path: Path | None,
        install_root: Path = INSTALL_ROOT,
        expected_uid: int = 0,
        expected_gid: int = 0,
        pkexec_path: Path = PKEXEC_PATH,
        bash_path: Path = BASH_PATH,
        python_path: Path = PYTHON_PATH,
        runner: InstallerRunner | None = None,
        timeout: float = 180.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.bundle_path = bundle_path
        self.install_root = install_root
        self.expected_uid = int(expected_uid)
        self.expected_gid = int(expected_gid)
        self.pkexec_path = pkexec_path
        self.bash_path = bash_path
        self.python_path = python_path
        self.runner = SubprocessInstallerRunner() if runner is None else runner
        self.timeout = float(timeout)
        self.environment = dict(os.environ if environment is None else environment)

    @classmethod
    def from_environment(cls) -> "PackagedHelperManager":
        raw = os.environ.get(BUNDLE_ENVIRONMENT_KEY, "").strip()
        return cls(bundle_path=Path(raw) if raw else None)

    @property
    def packaged(self) -> bool:
        return self.bundle_path is not None

    def audit(self) -> HelperInstallationAudit:
        if self.bundle_path is None:
            return HelperInstallationAudit(
                HelperInstallationState.UNMANAGED_SOURCE,
                packaged=False,
                details="Source-tree run: packaged helper compatibility gate is not active.",
            )
        try:
            manifest = self._load_verified_bundle_manifest()
        except Exception as exc:
            return HelperInstallationAudit(
                HelperInstallationState.BUNDLE_INVALID,
                packaged=True,
                details=f"{type(exc).__name__}: {exc}",
            )
        try:
            return self._audit_installed(manifest)
        except HelperInstallationUnsafeError as exc:
            return HelperInstallationAudit(
                HelperInstallationState.UNSAFE,
                packaged=True,
                details=str(exc),
            )

    def install_or_upgrade(self) -> HelperInstallationAudit:
        before = self.audit()
        if before.current:
            return before
        if before.state is HelperInstallationState.BUNDLE_INVALID:
            raise HelperBundleValidationError(before.details)
        if before.state is HelperInstallationState.UNSAFE:
            raise HelperInstallationUnsafeError(before.details)
        if not before.installable:
            raise HelperInstallationError(
                f"Helper installation is not permitted from state {before.state.value}."
            )

        manifest = self._load_verified_bundle_manifest()

        _verify_fixed_executable(self.pkexec_path, "pkexec executable")
        _verify_fixed_executable(self.bash_path, "bash executable")
        _verify_fixed_executable(
            self.python_path, "python executable", allow_safe_symlink=True
        )

        # Never execute a user-owned staged installer after authorization.
        # Anchor the privilege handoff to the verified AppImage manifest digest,
        # run only fixed root-owned system Python, copy verified bytes into a
        # root-owned /run tree, and execute only that root-owned installer copy.
        manifest_digest = _sha256(self._bundle_file(BUNDLE_MANIFEST_NAME))
        with self._stage_verified_bundle(manifest) as staged_bundle:
            arguments = [
                str(self.pkexec_path),
                "--disable-internal-agent",
                str(self.python_path),
                "-I",
                "-c",
                ROOT_STAGING_BOOTSTRAP,
                str(staged_bundle),
                manifest_digest,
                __version__,
            ]
            try:
                result = self.runner.run(
                    arguments,
                    timeout=self.timeout,
                    environment=_safe_environment(self.environment),
                )
            except subprocess.TimeoutExpired as exc:
                raise HelperInstallationError(
                    f"Kill Switch helper installation timed out after {self.timeout:g} seconds."
                ) from exc
            except OSError as exc:
                raise HelperInstallationError(
                    f"Could not start the Kill Switch helper installer: {exc}"
                ) from exc

            self._enforce_output_limit(result.stdout, "standard output")
            self._enforce_output_limit(result.stderr, "standard error")
            if result.returncode in {126, 127}:
                raise HelperInstallationAuthorizationDenied(
                    "Administrator authorization was cancelled or denied."
                )
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                raise HelperInstallationError(
                    "The Kill Switch helper installer failed"
                    + (f": {details}" if details else f" with status {result.returncode}.")
                )

        after = self.audit()
        if after.state is not HelperInstallationState.CURRENT:
            raise HelperInstallationError(
                "The helper installer returned success, but the installed helper does not "
                f"exactly match this AppImage ({after.state.value}: {after.details})."
            )
        return after

    def _load_verified_bundle_manifest(self) -> dict[str, object]:
        assert self.bundle_path is not None
        return self._load_verified_bundle_manifest_from(self.bundle_path)

    def _load_verified_bundle_manifest_from(self, bundle_path: Path) -> dict[str, object]:
        try:
            root_meta = bundle_path.lstat()
            root = bundle_path.resolve(strict=True)
        except OSError as exc:
            raise HelperBundleValidationError(
                f"Could not inspect the packaged helper bundle: {exc}"
            ) from exc
        if bundle_path.is_symlink() or not stat.S_ISDIR(root_meta.st_mode):
            raise HelperBundleValidationError("The packaged helper bundle is not a real directory.")

        manifest_path = root / BUNDLE_MANIFEST_NAME
        try:
            meta = manifest_path.lstat()
        except OSError as exc:
            raise HelperBundleValidationError("The packaged helper manifest is missing.") from exc
        if manifest_path.is_symlink() or not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
            raise HelperBundleValidationError("The packaged helper manifest is not a safe regular file.")
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HelperBundleValidationError("The packaged helper manifest is invalid JSON.") from exc
        expected_keys = {
            "schema_version",
            "app_version",
            "helper_stage",
            "protocol_version",
            "files",
        }
        if not isinstance(document, dict) or set(document) != expected_keys:
            raise HelperBundleValidationError("The packaged helper manifest shape is unexpected.")
        if document.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            raise HelperBundleValidationError("Unsupported packaged helper manifest schema.")
        if document.get("app_version") != __version__:
            raise HelperBundleValidationError(
                "The packaged helper payload belongs to a different PIA Bazzite version."
            )
        if document.get("helper_stage") != EXPECTED_HELPER_STAGE:
            raise HelperBundleValidationError("The packaged helper stage does not match this app.")
        if document.get("protocol_version") != EXPECTED_PROTOCOL_VERSION:
            raise HelperBundleValidationError("The packaged helper protocol does not match this app.")
        files = document.get("files")
        if not isinstance(files, dict) or set(files) != set(BUNDLE_SOURCE_MODES):
            raise HelperBundleValidationError("The packaged helper file list is incomplete or unexpected.")

        actual_files: set[str] = set()
        for candidate in root.rglob("*"):
            if candidate.is_dir():
                continue
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError as exc:
                raise HelperBundleValidationError("A packaged helper path escaped its bundle.") from exc
            actual_files.add(relative)
        expected_actual = set(BUNDLE_SOURCE_MODES) | {BUNDLE_MANIFEST_NAME}
        if actual_files != expected_actual:
            raise HelperBundleValidationError("The packaged helper bundle contains missing or extra files.")

        for relative, expected_mode in BUNDLE_SOURCE_MODES.items():
            candidate = root / relative
            try:
                metadata = candidate.lstat()
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise HelperBundleValidationError(
                    f"Could not inspect packaged helper file {relative}."
                ) from exc
            if resolved != root / relative:
                raise HelperBundleValidationError(f"Packaged helper file escaped the bundle: {relative}")
            if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise HelperBundleValidationError(f"Unsafe packaged helper file: {relative}")
            if stat.S_IMODE(metadata.st_mode) != expected_mode:
                raise HelperBundleValidationError(f"Wrong packaged helper mode: {relative}")
            expected_hash = files.get(relative)
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise HelperBundleValidationError(f"Invalid packaged helper checksum: {relative}")
            if _sha256(candidate) != expected_hash:
                raise HelperBundleValidationError(f"Packaged helper checksum mismatch: {relative}")
        return document

    def _bundle_file(self, relative: str) -> Path:
        assert self.bundle_path is not None
        return self._bundle_file_from(self.bundle_path, relative)

    @staticmethod
    def _bundle_file_from(bundle_path: Path, relative: str) -> Path:
        root = bundle_path.resolve(strict=True)
        candidate = (root / relative).resolve(strict=True)
        if candidate != root / relative:
            raise HelperBundleValidationError(f"Packaged helper file escaped the bundle: {relative}")
        return candidate

    @contextmanager
    def _stage_verified_bundle(self, manifest: Mapping[str, object]):
        assert self.bundle_path is not None
        with tempfile.TemporaryDirectory(
            prefix="pia-bazzite-helper-install-", dir="/tmp"
        ) as temporary:
            staged = Path(temporary)
            staged.chmod(0o700)
            for relative, mode in BUNDLE_SOURCE_MODES.items():
                source = self._bundle_file(relative)
                destination = staged / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                current = destination.parent
                while current != staged:
                    current.chmod(0o700)
                    current = current.parent
                shutil.copyfile(source, destination, follow_symlinks=False)
                destination.chmod(mode)

            source_manifest = self._bundle_file(BUNDLE_MANIFEST_NAME)
            staged_manifest = staged / BUNDLE_MANIFEST_NAME
            shutil.copyfile(source_manifest, staged_manifest, follow_symlinks=False)
            staged_manifest.chmod(0o644)

            staged_document = self._load_verified_bundle_manifest_from(staged)
            if staged_document != dict(manifest):
                raise HelperBundleValidationError(
                    "The staged helper bundle does not exactly match the mounted AppImage bundle."
                )
            yield staged

    def _audit_installed(self, bundle_manifest: Mapping[str, object]) -> HelperInstallationAudit:
        expected_hashes = self._expected_installed_hashes(bundle_manifest)
        all_paths = [self.install_root / relative for relative in INSTALLED_MODES]
        manifest_path = self.install_root / INSTALL_MANIFEST.name
        any_present = self.install_root.exists() or manifest_path.exists() or any(
            path.exists() or path.is_symlink() for path in all_paths
        )
        if not any_present:
            return HelperInstallationAudit(
                HelperInstallationState.MISSING,
                packaged=True,
                details="The fixed root-owned Kill Switch helper is not installed.",
            )

        if self.install_root.exists() or self.install_root.is_symlink():
            self._verify_installed_directory(self.install_root)
            self._verify_installed_directory(self.install_root.parent)
        else:
            return HelperInstallationAudit(
                HelperInstallationState.MISSING,
                packaged=True,
                details="The fixed helper directory is missing.",
            )

        package_dir = self.install_root / "pia_bazzite_kill_switch_helper"
        if package_dir.exists() or package_dir.is_symlink():
            self._verify_installed_directory(package_dir)

        missing = [
            relative
            for relative in INSTALLED_MODES
            if not (self.install_root / relative).exists()
            and not (self.install_root / relative).is_symlink()
        ]
        if not manifest_path.exists() and not manifest_path.is_symlink():
            missing.append(INSTALL_MANIFEST.name)

        for relative, mode in INSTALLED_MODES.items():
            path = self.install_root / relative
            if path.exists() or path.is_symlink():
                self._verify_installed_file(path, mode)
        if manifest_path.exists() or manifest_path.is_symlink():
            self._verify_installed_file(manifest_path, 0o644)

        if missing:
            return HelperInstallationAudit(
                HelperInstallationState.OUTDATED,
                packaged=True,
                details="The installed helper is incomplete: " + ", ".join(sorted(missing)),
            )

        actual_hashes = {relative: _sha256(self.install_root / relative) for relative in INSTALLED_MODES}
        if actual_hashes != expected_hashes:
            return HelperInstallationAudit(
                HelperInstallationState.OUTDATED,
                packaged=True,
                details="The installed helper files do not exactly match this AppImage.",
            )

        try:
            installed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return HelperInstallationAudit(
                HelperInstallationState.OUTDATED,
                packaged=True,
                details="The installed helper manifest is unreadable or invalid.",
            )
        expected_manifest = {
            "schema_version": INSTALL_SCHEMA_VERSION,
            "install_format": INSTALL_FORMAT,
            "helper_stage": EXPECTED_HELPER_STAGE,
            "protocol_version": EXPECTED_PROTOCOL_VERSION,
            "files": expected_hashes,
        }
        if installed_manifest != expected_manifest:
            return HelperInstallationAudit(
                HelperInstallationState.OUTDATED,
                packaged=True,
                details="The installed helper manifest does not exactly match this AppImage.",
            )
        return HelperInstallationAudit(
            HelperInstallationState.CURRENT,
            packaged=True,
            details="The installed Kill Switch helper exactly matches this AppImage.",
        )

    def _expected_installed_hashes(self, bundle_manifest: Mapping[str, object]) -> dict[str, str]:
        files = bundle_manifest.get("files")
        if not isinstance(files, dict):
            raise HelperBundleValidationError("Packaged helper manifest has no file map.")
        return {
            installed: str(files[source])
            for source, installed in SOURCE_TO_INSTALLED.items()
        }

    def _verify_installed_directory(self, path: Path) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise HelperInstallationUnsafeError(f"Could not inspect installed directory {path}: {exc}") from exc
        if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise HelperInstallationUnsafeError(f"Installed helper directory is unsafe: {path}")
        if metadata.st_uid != self.expected_uid or metadata.st_gid != self.expected_gid:
            raise HelperInstallationUnsafeError(f"Installed helper directory has the wrong owner: {path}")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise HelperInstallationUnsafeError(f"Installed helper directory is group/world writable: {path}")

    def _verify_installed_file(self, path: Path, expected_mode: int) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise HelperInstallationUnsafeError(f"Could not inspect installed helper file {path}: {exc}") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise HelperInstallationUnsafeError(f"Installed helper path is not a regular file: {path}")
        if metadata.st_uid != self.expected_uid or metadata.st_gid != self.expected_gid:
            raise HelperInstallationUnsafeError(f"Installed helper file has the wrong owner: {path}")
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise HelperInstallationUnsafeError(f"Installed helper file has an unsafe mode: {path}")
        if metadata.st_nlink != 1:
            raise HelperInstallationUnsafeError(f"Installed helper file has multiple hard links: {path}")

    @staticmethod
    def _enforce_output_limit(value: str, stream_name: str) -> None:
        if len(value.encode("utf-8", errors="replace")) > MAX_INSTALLER_OUTPUT_BYTES:
            raise HelperInstallationError(f"Helper installer {stream_name} exceeded the size limit.")


__all__ = [
    "BASH_PATH",
    "BUNDLE_ENVIRONMENT_KEY",
    "BUNDLE_SOURCE_MODES",
    "HelperBundleValidationError",
    "HelperInstallationAudit",
    "HelperInstallationAuthorizationDenied",
    "HelperInstallationError",
    "HelperInstallationState",
    "HelperInstallationUnsafeError",
    "INSTALL_ROOT",
    "INSTALLED_MODES",
    "PackagedHelperManager",
    "PKEXEC_PATH",
    "PYTHON_PATH",
    "ROOT_STAGING_BOOTSTRAP",
    "SOURCE_TO_INSTALLED",
]
