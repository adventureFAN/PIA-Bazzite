from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Mapping, Protocol, Sequence

PKEXEC_PATH = Path("/usr/bin/pkexec")
HELPER_PATH = Path(
    "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper"
)
EXPECTED_PROTOCOL_VERSION = 1
EXPECTED_SCHEMA_VERSION = 1
EXPECTED_HELPER_STAGE = 5
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_OUTPUT_BYTES = 128 * 1024
IPV6_GUARD_TABLE_NAME = "pia_bazzite_ipv6_guard"

_ACTIONS = {
    "status",
    "enable",
    "set-interfaces",
    "set-endpoints",
    "add-endpoint",
    "remove-endpoint",
    "disable",
    "emergency-reset",
    "ipv6-guard-status",
    "ipv6-guard-enable",
    "ipv6-guard-disable",
}
_DANGEROUS_ENVIRONMENT_KEYS = {
    "APPDIR",
    "APPIMAGE",
    "ARGV0",
    "GCONV_PATH",
    "GI_TYPELIB_PATH",
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "PYTHONHOME",
    "PYTHONPATH",
    "PIA_BAZZITE_HELPER_BUNDLE",
    "QML2_IMPORT_PATH",
    "QT_PLUGIN_PATH",
}


class KillSwitchClientError(RuntimeError):
    """Base class for failures at the unprivileged helper-client boundary."""


class HelperNotInstalledError(KillSwitchClientError):
    """Raised when the fixed helper installation is missing or unsafe."""


class PkexecUnavailableError(KillSwitchClientError):
    """Raised when the fixed pkexec binary is unavailable or unsafe."""


class AuthorizationDeniedError(KillSwitchClientError):
    """Raised when Polkit authorization was cancelled or denied."""


class HelperTimeoutError(KillSwitchClientError):
    """Raised when the helper invocation exceeds the fixed timeout."""


class InvalidHelperResponseError(KillSwitchClientError):
    """Raised when helper output is absent, malformed, or internally inconsistent."""


class ProtocolMismatchError(InvalidHelperResponseError):
    """Raised when the installed helper speaks an unsupported protocol."""


class HelperCommandError(KillSwitchClientError):
    """A structured error returned by the privileged helper."""

    def __init__(
        self,
        *,
        action: str,
        kind: str,
        message: str,
        returncode: int,
        payload: Mapping[str, Any],
    ) -> None:
        super().__init__(message)
        self.action = action
        self.kind = kind
        self.message = message
        self.returncode = returncode
        self.payload = dict(payload)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> ProcessResult:
        """Run one fixed argv without a shell."""


class SubprocessRunner:
    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> ProcessResult:
        completed = subprocess.run(
            list(arguments),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=dict(environment),
        )
        return ProcessResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True, slots=True)
class HelperResponse:
    action: str
    returncode: int
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class KillSwitchStatus:
    action: str
    state: str
    present: bool
    verified: bool
    table: str
    table_generation: int
    capabilities: tuple[str, ...]
    problems: tuple[str, ...]
    payload: Mapping[str, Any]
    physical_interfaces: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()

    @property
    def protection_active(self) -> bool:
        return (
            self.state == "active"
            and self.present
            and self.verified
            and not self.problems
        )

    @classmethod
    def from_response(cls, response: HelperResponse) -> "KillSwitchStatus":
        payload = response.payload
        state = _require_string(payload, "state")
        if state not in {"active", "disabled"}:
            raise InvalidHelperResponseError(
                f"Helper returned unsupported state {state!r}."
            )
        present = _require_bool(payload, "present")
        verified = _require_bool(payload, "verified")
        table = _require_string(payload, "table")
        table_generation = _require_int(payload, "table_generation")
        capabilities = _require_string_tuple(payload, "capabilities")
        problems = _require_string_tuple(payload, "problems")
        physical_interfaces = _require_string_tuple(payload, "physical_interfaces")
        endpoints = _require_string_tuple(payload, "endpoints")

        if not verified:
            raise InvalidHelperResponseError(
                "Helper response is not structurally verified."
            )
        if problems:
            raise InvalidHelperResponseError(
                "Helper response reports structural problems: " + "; ".join(problems)
            )
        if state == "active" and not present:
            raise InvalidHelperResponseError(
                "Helper claims an active state while its table is absent."
            )
        if state == "disabled" and present:
            raise InvalidHelperResponseError(
                "Helper claims a disabled state while its table is present."
            )
        if "inspect-route" not in capabilities:
            raise InvalidHelperResponseError(
                "Helper response does not support exact firewall-route inspection."
            )
        if state == "active" and (not physical_interfaces or not endpoints):
            raise InvalidHelperResponseError(
                "Active helper response does not contain exact firewall allowlists."
            )
        if state == "disabled" and (physical_interfaces or endpoints):
            raise InvalidHelperResponseError(
                "Disabled helper response unexpectedly contains firewall allowlists."
            )

        return cls(
            action=response.action,
            state=state,
            present=present,
            verified=verified,
            table=table,
            table_generation=table_generation,
            capabilities=capabilities,
            problems=problems,
            payload=dict(payload),
            physical_interfaces=physical_interfaces,
            endpoints=endpoints,
        )


@dataclass(frozen=True, slots=True)
class IPv6GuardStatus:
    action: str
    state: str
    present: bool
    verified: bool
    table: str
    table_generation: int
    capabilities: tuple[str, ...]
    problems: tuple[str, ...]
    payload: Mapping[str, Any]

    @property
    def protection_active(self) -> bool:
        return (
            self.state == "active"
            and self.present
            and self.verified
            and not self.problems
        )

    @classmethod
    def from_response(cls, response: HelperResponse) -> "IPv6GuardStatus":
        payload = response.payload
        state = _require_string(payload, "state")
        if state not in {"active", "disabled"}:
            raise InvalidHelperResponseError(
                f"Helper returned unsupported IPv6 guard state {state!r}."
            )
        present = _require_bool(payload, "present")
        verified = _require_bool(payload, "verified")
        table = _require_string(payload, "table")
        table_generation = _require_int(payload, "table_generation")
        capabilities = _require_string_tuple(payload, "capabilities")
        problems = _require_string_tuple(payload, "problems")

        if table != IPV6_GUARD_TABLE_NAME:
            raise InvalidHelperResponseError(
                f"Helper returned unexpected IPv6 guard table {table!r}."
            )
        if not verified:
            raise InvalidHelperResponseError(
                "IPv6 guard response is not structurally verified."
            )
        if problems:
            raise InvalidHelperResponseError(
                "IPv6 guard response reports structural problems: " + "; ".join(problems)
            )
        if state == "active" and not present:
            raise InvalidHelperResponseError(
                "Helper claims an active IPv6 guard while its table is absent."
            )
        if state == "disabled" and present:
            raise InvalidHelperResponseError(
                "Helper claims a disabled IPv6 guard while its table is present."
            )
        if "ipv6-only-guard" not in capabilities:
            raise InvalidHelperResponseError(
                "Helper response does not advertise the IPv6-only guard capability."
            )

        return cls(
            action=response.action,
            state=state,
            present=present,
            verified=verified,
            table=table,
            table_generation=table_generation,
            capabilities=capabilities,
            problems=problems,
            payload=dict(payload),
        )


class KillSwitchClient:
    """Strict unprivileged client for the fixed Polkit helper protocol."""

    def __init__(
        self,
        *,
        helper_path: Path = HELPER_PATH,
        pkexec_path: Path = PKEXEC_PATH,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        runner: ProcessRunner | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if timeout <= 0 or timeout > 300:
            raise ValueError("Helper timeout must be greater than 0 and at most 300 seconds.")
        self.helper_path = helper_path
        self.pkexec_path = pkexec_path
        self.timeout = float(timeout)
        self.runner = runner if runner is not None else SubprocessRunner()
        self.environment = dict(os.environ if environment is None else environment)

    def status(self) -> KillSwitchStatus:
        return self._status_action("status")

    def enable(
        self,
        *,
        interfaces: Sequence[str],
        endpoints: Sequence[str],
    ) -> KillSwitchStatus:
        arguments = _repeated_arguments("--interface", interfaces)
        arguments.extend(_repeated_arguments("--endpoint", endpoints))
        return self._status_action("enable", arguments)

    def set_interfaces(self, interfaces: Sequence[str]) -> KillSwitchStatus:
        return self._status_action(
            "set-interfaces",
            _repeated_arguments("--interface", interfaces),
        )

    def set_endpoints(self, endpoints: Sequence[str]) -> KillSwitchStatus:
        return self._status_action(
            "set-endpoints",
            _repeated_arguments("--endpoint", endpoints),
        )

    def add_endpoint(self, endpoint: str) -> KillSwitchStatus:
        return self._status_action(
            "add-endpoint",
            ["--endpoint", _safe_argument(endpoint)],
        )

    def remove_endpoint(self, endpoint: str) -> KillSwitchStatus:
        return self._status_action(
            "remove-endpoint",
            ["--endpoint", _safe_argument(endpoint)],
        )

    def disable(self) -> KillSwitchStatus:
        return self._status_action("disable")

    def emergency_reset(self) -> KillSwitchStatus:
        return self._status_action("emergency-reset")

    def ipv6_guard_status(self) -> IPv6GuardStatus:
        return self._ipv6_guard_action("ipv6-guard-status")

    def ipv6_guard_enable(self) -> IPv6GuardStatus:
        return self._ipv6_guard_action("ipv6-guard-enable")

    def ipv6_guard_disable(self) -> IPv6GuardStatus:
        return self._ipv6_guard_action("ipv6-guard-disable")

    def _ipv6_guard_action(self, action: str) -> IPv6GuardStatus:
        response = self._invoke(action, ())
        status = IPv6GuardStatus.from_response(response)
        expected_state = (
            "active" if action == "ipv6-guard-enable" else
            "disabled" if action == "ipv6-guard-disable" else None
        )
        if expected_state is not None and status.state != expected_state:
            raise InvalidHelperResponseError(
                f"Action {action!r} returned state {status.state!r}, "
                f"expected {expected_state!r}."
            )
        return status

    def _status_action(
        self,
        action: str,
        arguments: Sequence[str] = (),
    ) -> KillSwitchStatus:
        response = self._invoke(action, arguments)
        status = KillSwitchStatus.from_response(response)
        expected_state = "disabled" if action in {"disable", "emergency-reset"} else None
        if action in {
            "enable",
            "set-interfaces",
            "set-endpoints",
            "add-endpoint",
            "remove-endpoint",
        }:
            expected_state = "active"
        if expected_state is not None and status.state != expected_state:
            raise InvalidHelperResponseError(
                f"Action {action!r} returned state {status.state!r}, "
                f"expected {expected_state!r}."
            )
        return status

    def _invoke(self, action: str, arguments: Sequence[str]) -> HelperResponse:
        if action not in _ACTIONS:
            raise ValueError(f"Unsupported helper action: {action}")
        self._preflight()
        argv = [
            str(self.pkexec_path),
            "--disable-internal-agent",
            str(self.helper_path),
            action,
            *arguments,
        ]
        try:
            result = self.runner.run(
                argv,
                timeout=self.timeout,
                environment=_safe_environment(self.environment),
            )
        except subprocess.TimeoutExpired as exc:
            raise HelperTimeoutError(
                f"Kill-switch helper timed out after {self.timeout:g} seconds."
            ) from exc
        except FileNotFoundError as exc:
            raise PkexecUnavailableError(
                f"Could not execute the fixed pkexec binary: {self.pkexec_path}"
            ) from exc
        except OSError as exc:
            raise KillSwitchClientError(
                f"Could not execute the kill-switch helper: {exc}"
            ) from exc

        _enforce_output_limit(result.stdout, "standard output")
        _enforce_output_limit(result.stderr, "standard error")

        if result.returncode in {126, 127} and not _contains_protocol_json(
            result.stdout, result.stderr
        ):
            raise AuthorizationDeniedError(
                "Polkit authorization was cancelled or denied."
            )

        payload = _parse_result_payload(result)
        _validate_envelope(payload, expected_action=action)

        ok = payload["ok"]
        if result.returncode == 0 and not ok:
            raise InvalidHelperResponseError(
                "Helper returned an error payload with a successful exit status."
            )
        if result.returncode != 0 and ok:
            raise InvalidHelperResponseError(
                "Helper returned a success payload with a failing exit status."
            )
        if not ok:
            raise HelperCommandError(
                action=action,
                kind=_require_string(payload, "error"),
                message=_require_string(payload, "message"),
                returncode=result.returncode,
                payload=payload,
            )
        return HelperResponse(action=action, returncode=result.returncode, payload=payload)

    def _preflight(self) -> None:
        _verify_executable(
            self.pkexec_path,
            role="pkexec",
            error_type=PkexecUnavailableError,
            exact_mode=None,
        )
        _verify_executable(
            self.helper_path,
            role="installed helper",
            error_type=HelperNotInstalledError,
            exact_mode=0o755,
        )


def _verify_executable(
    path: Path,
    *,
    role: str,
    error_type: type[KillSwitchClientError],
    exact_mode: int | None,
) -> None:
    if not path.is_absolute():
        raise error_type(f"The fixed {role} path is not absolute: {path}")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise error_type(f"The fixed {role} is unavailable: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise error_type(f"The fixed {role} path is not a regular file: {path}")
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise error_type(f"The fixed {role} is not owned by root:root: {path}")
    if metadata.st_nlink != 1:
        raise error_type(f"The fixed {role} must have exactly one hard link: {path}")
    if exact_mode is not None and mode != exact_mode:
        raise error_type(
            f"The fixed {role} has mode {mode:04o}, expected {exact_mode:04o}: {path}"
        )
    if exact_mode is None and mode & 0o022:
        raise error_type(f"The fixed {role} is group- or world-writable: {path}")
    if mode & 0o111 == 0:
        raise error_type(f"The fixed {role} is not executable: {path}")


def _safe_argument(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Helper arguments must be strings.")
    if not value or len(value) > 255:
        raise ValueError("Helper arguments must contain 1-255 characters.")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError("Helper arguments must not contain whitespace padding or control characters.")
    return value


def _repeated_arguments(flag: str, values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError("Expected a sequence of helper argument strings.")
    normalized = [_safe_argument(value) for value in values]
    if not normalized:
        raise ValueError(f"At least one value is required for {flag}.")
    arguments: list[str] = []
    for value in normalized:
        arguments.extend((flag, value))
    return arguments


def _safe_environment(source: Mapping[str, str]) -> dict[str, str]:
    environment: dict[str, str] = {}
    for key, value in source.items():
        if key in _DANGEROUS_ENVIRONMENT_KEYS or key.startswith("LD_"):
            continue
        if key.startswith("SUDO_"):
            continue
        environment[key] = value
    environment["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    return environment


def _enforce_output_limit(value: str, stream_name: str) -> None:
    if len(value.encode("utf-8", errors="replace")) > MAX_OUTPUT_BYTES:
        raise InvalidHelperResponseError(
            f"Helper {stream_name} exceeded the maximum accepted size."
        )


def _parse_json_document(value: str) -> dict[str, Any]:
    stripped = value.strip()
    if not stripped:
        raise InvalidHelperResponseError("Helper returned no JSON document.")
    try:
        document = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise InvalidHelperResponseError(
            "Helper returned malformed or mixed JSON output."
        ) from exc
    if not isinstance(document, dict):
        raise InvalidHelperResponseError("Helper response must be one JSON object.")
    return document


def _contains_protocol_json(stdout: str, stderr: str) -> bool:
    for value in (stdout, stderr):
        try:
            payload = _parse_json_document(value)
        except InvalidHelperResponseError:
            continue
        if {
            "ok",
            "schema_version",
            "protocol_version",
            "helper_stage",
            "action",
        }.issubset(payload):
            return True
    return False


def _parse_result_payload(result: ProcessResult) -> dict[str, Any]:
    if result.returncode == 0:
        if result.stderr.strip():
            raise InvalidHelperResponseError(
                "Successful helper execution produced unexpected standard-error output."
            )
        return _parse_json_document(result.stdout)
    if result.stdout.strip():
        raise InvalidHelperResponseError(
            "Failed helper execution produced unexpected standard-output data."
        )
    return _parse_json_document(result.stderr)


def _validate_envelope(payload: Mapping[str, Any], *, expected_action: str) -> None:
    required = {
        "ok",
        "schema_version",
        "protocol_version",
        "helper_stage",
        "action",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise InvalidHelperResponseError(
            "Helper response is missing fields: " + ", ".join(missing)
        )
    if _require_int(payload, "schema_version") != EXPECTED_SCHEMA_VERSION:
        raise ProtocolMismatchError("Unsupported helper response schema version.")
    if _require_int(payload, "protocol_version") != EXPECTED_PROTOCOL_VERSION:
        raise ProtocolMismatchError("Unsupported kill-switch helper protocol version.")
    if _require_int(payload, "helper_stage") != EXPECTED_HELPER_STAGE:
        raise ProtocolMismatchError("Installed helper stage does not match this application.")
    if _require_string(payload, "action") != expected_action:
        raise InvalidHelperResponseError(
            "Helper response action does not match the request."
        )
    _require_bool(payload, "ok")


def _require_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise InvalidHelperResponseError(f"Helper field {key!r} must be boolean.")
    return value


def _require_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidHelperResponseError(f"Helper field {key!r} must be an integer.")
    return value


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidHelperResponseError(
            f"Helper field {key!r} must be a non-empty string."
        )
    return value


def _require_string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise InvalidHelperResponseError(
            f"Helper field {key!r} must be a list of non-empty strings."
        )
    return tuple(value)


__all__ = [
    "IPv6GuardStatus",
    "AuthorizationDeniedError",
    "DEFAULT_TIMEOUT_SECONDS",
    "EXPECTED_HELPER_STAGE",
    "EXPECTED_PROTOCOL_VERSION",
    "EXPECTED_SCHEMA_VERSION",
    "HELPER_PATH",
    "HelperCommandError",
    "HelperNotInstalledError",
    "HelperResponse",
    "HelperTimeoutError",
    "InvalidHelperResponseError",
    "KillSwitchClient",
    "KillSwitchClientError",
    "KillSwitchStatus",
    "PKEXEC_PATH",
    "PkexecUnavailableError",
    "ProcessResult",
    "ProcessRunner",
    "ProtocolMismatchError",
    "SubprocessRunner",
]
