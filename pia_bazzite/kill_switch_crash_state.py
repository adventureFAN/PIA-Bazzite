from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping
import uuid

from .kill_switch_client import KillSwitchStatus
from .kill_switch_recovery import FirewallRoutePlan, UnsafeRecoveryPlanError
from .network_probes import NetworkProbeBaseline


RECORD_KIND = "pia-bazzite-kill-switch-crash-recovery"
RECORD_SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 16 * 1024
_RECORD_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "session_id",
        "phase",
        "profile_uuid",
        "physical_interfaces",
        "endpoints",
        "checksum",
    }
)


class CrashRecoveryStateError(RuntimeError):
    """A crash-recovery record is unsafe, malformed, or inconsistent."""


class CrashRecoveryPhase(str, Enum):
    PROTECTED_CONNECTED = "protected-connected"
    PROTECTED_BLOCKING = "protected-blocking"


@dataclass(frozen=True, slots=True)
class CrashRecoveryRecord:
    """Unprivileged recovery hint that must never be trusted on its own.

    The record survives a hard GUI crash and preserves only the exact route and
    NetworkManager profile that the previous process intended to protect.  A
    restarted process may use it only after independently verifying the live
    helper table and NetworkManager state.
    """

    session_id: str
    phase: CrashRecoveryPhase
    profile_uuid: str
    physical_interfaces: tuple[str, ...]
    endpoints: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        phase: CrashRecoveryPhase,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
        session_id: str | None = None,
    ) -> "CrashRecoveryRecord":
        if not isinstance(phase, CrashRecoveryPhase):
            raise CrashRecoveryStateError("Unsupported crash-recovery phase.")
        profile = _canonical_uuid(profile_uuid, "profile UUID")
        session = _canonical_uuid(session_id or str(uuid.uuid4()), "session ID")
        try:
            route = FirewallRoutePlan.create(
                physical_interfaces=route_plan.physical_interfaces,
                endpoints=route_plan.endpoints,
            )
        except (AttributeError, UnsafeRecoveryPlanError) as exc:
            raise CrashRecoveryStateError(
                f"Unsafe crash-recovery route plan: {exc}"
            ) from exc
        return cls(
            session_id=session,
            phase=phase,
            profile_uuid=profile,
            physical_interfaces=route.physical_interfaces,
            endpoints=route.endpoints,
        )

    @property
    def route_plan(self) -> FirewallRoutePlan:
        try:
            return FirewallRoutePlan.create(
                physical_interfaces=self.physical_interfaces,
                endpoints=self.endpoints,
            )
        except UnsafeRecoveryPlanError as exc:
            raise CrashRecoveryStateError(str(exc)) from exc

    @property
    def conservative_probe_baseline(self) -> NetworkProbeBaseline:
        # After a crash the original pre-firewall baseline cannot be trusted or
        # recaptured.  Requiring every fixed path to be blocked is conservative:
        # it can refuse an unlock, but it cannot silently omit IPv6 or DNS.
        return NetworkProbeBaseline(
            ipv4_tcp=True,
            ipv6_tcp=True,
            dns_tcp=True,
            dns_udp=True,
        )

    def _unsigned_document(self) -> dict[str, Any]:
        return {
            "kind": RECORD_KIND,
            "schema_version": RECORD_SCHEMA_VERSION,
            "session_id": self.session_id,
            "phase": self.phase.value,
            "profile_uuid": self.profile_uuid,
            "physical_interfaces": list(self.physical_interfaces),
            "endpoints": list(self.endpoints),
        }

    def to_document(self) -> dict[str, Any]:
        document = self._unsigned_document()
        document["checksum"] = _document_checksum(document)
        return document

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "CrashRecoveryRecord":
        if not isinstance(document, Mapping):
            raise CrashRecoveryStateError("Crash-recovery record must be a JSON object.")
        if set(document) != _RECORD_KEYS:
            raise CrashRecoveryStateError(
                "Crash-recovery record has missing or unexpected fields."
            )
        if document.get("kind") != RECORD_KIND:
            raise CrashRecoveryStateError("Crash-recovery record identity is invalid.")
        if document.get("schema_version") != RECORD_SCHEMA_VERSION:
            raise CrashRecoveryStateError("Crash-recovery record schema is unsupported.")

        checksum = document.get("checksum")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise CrashRecoveryStateError("Crash-recovery checksum is invalid.")
        unsigned = {key: document[key] for key in document if key != "checksum"}
        expected = _document_checksum(unsigned)
        if not _constant_time_equal(checksum, expected):
            raise CrashRecoveryStateError("Crash-recovery checksum does not match.")

        try:
            phase = CrashRecoveryPhase(document["phase"])
        except (TypeError, ValueError) as exc:
            raise CrashRecoveryStateError("Crash-recovery phase is invalid.") from exc

        interfaces = _require_string_list(document["physical_interfaces"], "interfaces")
        endpoints = _require_string_list(document["endpoints"], "endpoints")
        try:
            route = FirewallRoutePlan.create(
                physical_interfaces=interfaces,
                endpoints=endpoints,
            )
        except UnsafeRecoveryPlanError as exc:
            raise CrashRecoveryStateError(str(exc)) from exc

        return cls.create(
            phase=phase,
            profile_uuid=_require_string(document["profile_uuid"], "profile UUID"),
            route_plan=route,
            session_id=_require_string(document["session_id"], "session ID"),
        )


class CrashRecoveryStore:
    """Atomic 0600 storage for one fixed crash-recovery record path."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise CrashRecoveryStateError("Crash-recovery path must be absolute.")

    def save(self, record: CrashRecoveryRecord) -> None:
        if not isinstance(record, CrashRecoveryRecord):
            raise CrashRecoveryStateError("Expected a validated crash-recovery record.")
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require_safe_parent(parent)
        if self.path.exists() or self.path.is_symlink():
            _require_safe_record_path(self.path)

        raw = (
            json.dumps(
                record.to_document(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("ascii")
        if len(raw) > MAX_RECORD_BYTES:
            raise CrashRecoveryStateError("Crash-recovery record exceeds its size limit.")

        temporary = parent / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                descriptor = -1
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600, follow_symlinks=False)
            _fsync_directory(parent)
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery record could not be saved safely: {exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def load(self) -> CrashRecoveryRecord | None:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery record could not be inspected: {exc}"
            ) from exc
        _validate_record_metadata(self.path, metadata)

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags)
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                opened = os.fstat(handle.fileno())
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise CrashRecoveryStateError(
                        "Crash-recovery record changed while it was being opened."
                    )
                raw = handle.read(MAX_RECORD_BYTES + 1)
        except CrashRecoveryStateError:
            raise
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery record could not be read safely: {exc}"
            ) from exc

        if len(raw) > MAX_RECORD_BYTES:
            raise CrashRecoveryStateError("Crash-recovery record exceeds its size limit.")
        try:
            document = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CrashRecoveryStateError("Crash-recovery record is not valid JSON.") from exc
        return CrashRecoveryRecord.from_document(document)

    def clear(self) -> None:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery record could not be inspected: {exc}"
            ) from exc
        _validate_record_metadata(self.path, metadata)
        try:
            self.path.unlink()
            _fsync_directory(self.path.parent)
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery record could not be removed safely: {exc}"
            ) from exc

    def discard_untrusted_after_verified_release(self) -> None:
        """Remove only the fixed path entry after the host lock is proven absent.

        Normal record operations deliberately reject symlinks, broad permissions,
        malformed JSON, and other unsafe metadata.  After an independent host-side
        proof has established that both VPN and production firewall protection are
        absent, however, a malformed path entry must not permanently trap the GUI in
        a stale recovery error.  This cleanup never follows the entry: it unlinks only
        the fixed crash-recovery pathname inside the already private user-owned state
        directory.  Directories and special files remain refused.
        """

        parent = self.path.parent
        _require_safe_parent(parent)
        if self.path.name in {"", ".", ".."}:
            raise CrashRecoveryStateError("Crash-recovery record path is invalid.")
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery path could not be inspected for verified cleanup: {exc}"
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            raise CrashRecoveryStateError(
                "Crash-recovery path is a directory and was not removed."
            )
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)):
            raise CrashRecoveryStateError(
                "Crash-recovery path is a special file and was not removed."
            )
        try:
            self.path.unlink()
            _fsync_directory(parent)
        except OSError as exc:
            raise CrashRecoveryStateError(
                f"Crash-recovery path could not be removed after verified release: {exc}"
            ) from exc


class CrashRecoveryDisposition(str, Enum):
    NO_RECOVERY = "no-recovery"
    CLEAR_STALE_RECORD = "clear-stale-record"
    ADOPT_CONNECTED = "adopt-connected"
    ADOPT_BLOCKING = "adopt-blocking"
    REFUSE_UNOWNED_LOCK = "refuse-unowned-lock"
    REFUSE_UNVERIFIED_LOCK = "refuse-unverified-lock"
    REFUSE_ROUTE_MISMATCH = "refuse-route-mismatch"
    REFUSE_PROFILE_MISMATCH = "refuse-profile-mismatch"
    REFUSE_INCONSISTENT_HOST = "refuse-inconsistent-host"


@dataclass(frozen=True, slots=True)
class CrashRecoveryDecision:
    disposition: CrashRecoveryDisposition
    reason: str
    route_plan: FirewallRoutePlan | None = None
    probe_baseline: NetworkProbeBaseline | None = None
    profile_uuid: str = ""

    @property
    def adopted(self) -> bool:
        return self.disposition in {
            CrashRecoveryDisposition.ADOPT_CONNECTED,
            CrashRecoveryDisposition.ADOPT_BLOCKING,
        }


class CrashRecoveryVerifier:
    """Pure fail-closed reconciliation of record, helper, and NetworkManager."""

    def evaluate(
        self,
        *,
        record: CrashRecoveryRecord | None,
        helper_status: KillSwitchStatus,
        vpn_connected: bool,
        active_profile_uuid: str = "",
    ) -> CrashRecoveryDecision:
        if not isinstance(helper_status, KillSwitchStatus):
            return _decision(
                CrashRecoveryDisposition.REFUSE_UNVERIFIED_LOCK,
                "No validated helper status is available.",
            )
        if not helper_status.verified or helper_status.problems:
            return _decision(
                CrashRecoveryDisposition.REFUSE_UNVERIFIED_LOCK,
                "The production firewall table is not structurally verified.",
            )

        if not helper_status.present:
            if vpn_connected:
                return _decision(
                    CrashRecoveryDisposition.REFUSE_INCONSISTENT_HOST,
                    "NetworkManager reports a VPN while the production firewall table is absent.",
                )
            if record is None:
                return _decision(
                    CrashRecoveryDisposition.NO_RECOVERY,
                    "No production firewall table or crash-recovery record is present.",
                )
            return _decision(
                CrashRecoveryDisposition.CLEAR_STALE_RECORD,
                "The production firewall table is absent; the stale record may be cleared.",
            )

        if not helper_status.protection_active:
            return _decision(
                CrashRecoveryDisposition.REFUSE_UNVERIFIED_LOCK,
                "The production firewall table is present but active protection is not verified.",
            )
        if record is None:
            return _decision(
                CrashRecoveryDisposition.REFUSE_UNOWNED_LOCK,
                "A verified production firewall table exists without a recovery record.",
            )

        route = record.route_plan
        if (
            tuple(helper_status.physical_interfaces) != route.physical_interfaces
            or tuple(helper_status.endpoints) != route.endpoints
        ):
            return _decision(
                CrashRecoveryDisposition.REFUSE_ROUTE_MISMATCH,
                "The live firewall allowlists do not exactly match the recovery record.",
            )

        baseline = record.conservative_probe_baseline
        if vpn_connected:
            try:
                active_profile = _canonical_uuid(active_profile_uuid, "active profile UUID")
            except CrashRecoveryStateError:
                return _decision(
                    CrashRecoveryDisposition.REFUSE_PROFILE_MISMATCH,
                    "The active NetworkManager profile UUID is missing or invalid.",
                )
            if active_profile != record.profile_uuid:
                return _decision(
                    CrashRecoveryDisposition.REFUSE_PROFILE_MISMATCH,
                    "The active NetworkManager profile does not match the recovery record.",
                )
            return CrashRecoveryDecision(
                disposition=CrashRecoveryDisposition.ADOPT_CONNECTED,
                reason="The connected VPN, exact firewall route, and recovery record match.",
                route_plan=route,
                probe_baseline=baseline,
                profile_uuid=record.profile_uuid,
            )

        if active_profile_uuid.strip():
            return _decision(
                CrashRecoveryDisposition.REFUSE_INCONSISTENT_HOST,
                "NetworkManager reports an active profile UUID while the VPN is disconnected.",
            )
        return CrashRecoveryDecision(
            disposition=CrashRecoveryDisposition.ADOPT_BLOCKING,
            reason="The VPN is down and the exact verified firewall route remains active.",
            route_plan=route,
            probe_baseline=baseline,
            profile_uuid=record.profile_uuid,
        )


class CrashRecoveryJournal:
    """Small persistence boundary used by the GUI after verified transitions.

    The journal never changes NetworkManager or firewall state.  It writes only
    a user-owned hint that a future process must independently reconcile.
    """

    def __init__(
        self,
        store: CrashRecoveryStore,
        *,
        session_id: str | None = None,
    ) -> None:
        if not isinstance(store, CrashRecoveryStore):
            raise CrashRecoveryStateError("Expected a crash-recovery store.")
        self.store = store
        self.session_id = _canonical_uuid(
            session_id or str(uuid.uuid4()),
            "session ID",
        )

    def save(
        self,
        *,
        phase: CrashRecoveryPhase,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
    ) -> CrashRecoveryRecord:
        record = CrashRecoveryRecord.create(
            phase=phase,
            profile_uuid=profile_uuid,
            route_plan=route_plan,
            session_id=self.session_id,
        )
        self.store.save(record)
        return record

    def save_connected(
        self,
        *,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
    ) -> CrashRecoveryRecord:
        return self.save(
            phase=CrashRecoveryPhase.PROTECTED_CONNECTED,
            profile_uuid=profile_uuid,
            route_plan=route_plan,
        )

    def save_blocking(
        self,
        *,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
    ) -> CrashRecoveryRecord:
        return self.save(
            phase=CrashRecoveryPhase.PROTECTED_BLOCKING,
            profile_uuid=profile_uuid,
            route_plan=route_plan,
        )

    def clear(self) -> None:
        self.store.clear()


def _decision(
    disposition: CrashRecoveryDisposition,
    reason: str,
) -> CrashRecoveryDecision:
    return CrashRecoveryDecision(disposition=disposition, reason=reason)


def _document_checksum(document: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("ascii"), right.encode("ascii"))


def _canonical_uuid(value: str, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise CrashRecoveryStateError(f"{label.capitalize()} is missing or invalid.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise CrashRecoveryStateError(f"{label.capitalize()} is invalid.") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise CrashRecoveryStateError(f"{label.capitalize()} must use canonical UUID syntax.")
    return canonical


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise CrashRecoveryStateError(f"Crash-recovery {label} must be a string.")
    return value


def _require_string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CrashRecoveryStateError(
            f"Crash-recovery {label} must be a list of strings."
        )
    return tuple(value)


def _require_safe_parent(parent: Path) -> None:
    try:
        metadata = parent.stat()
    except OSError as exc:
        raise CrashRecoveryStateError(
            f"Crash-recovery directory could not be inspected: {exc}"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise CrashRecoveryStateError("Crash-recovery parent is not a directory.")
    if metadata.st_uid != os.geteuid():
        raise CrashRecoveryStateError("Crash-recovery directory is not owned by this user.")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise CrashRecoveryStateError(
            "Crash-recovery directory must not be group- or world-writable."
        )


def _require_safe_record_path(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CrashRecoveryStateError(
            f"Crash-recovery record could not be inspected: {exc}"
        ) from exc
    _validate_record_metadata(path, metadata)


def _validate_record_metadata(path: Path, metadata: os.stat_result) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CrashRecoveryStateError("Crash-recovery record must be a regular file.")
    if metadata.st_uid != os.geteuid():
        raise CrashRecoveryStateError("Crash-recovery record is not owned by this user.")
    if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CrashRecoveryStateError("Crash-recovery record permissions are too broad.")
    if metadata.st_size > MAX_RECORD_BYTES:
        raise CrashRecoveryStateError("Crash-recovery record exceeds its size limit.")
    if path.name in {"", ".", ".."}:
        raise CrashRecoveryStateError("Crash-recovery record path is invalid.")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CrashRecoveryDecision",
    "CrashRecoveryDisposition",
    "CrashRecoveryJournal",
    "CrashRecoveryPhase",
    "CrashRecoveryRecord",
    "CrashRecoveryStateError",
    "CrashRecoveryStore",
    "CrashRecoveryVerifier",
    "MAX_RECORD_BYTES",
    "RECORD_KIND",
    "RECORD_SCHEMA_VERSION",
]
