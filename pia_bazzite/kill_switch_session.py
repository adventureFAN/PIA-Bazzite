from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time
from typing import Any, Mapping, Protocol, Sequence

from .kill_switch_client import (
    AuthorizationDeniedError,
    DEFAULT_TIMEOUT_SECONDS,
    EXPECTED_HELPER_STAGE,
    EXPECTED_PROTOCOL_VERSION,
    HelperCommandError,
    HelperNotInstalledError,
    HelperResponse,
    HelperTimeoutError,
    InvalidHelperResponseError,
    KillSwitchClientError,
    KillSwitchStatus,
    PKEXEC_PATH,
    PkexecUnavailableError,
    ProtocolMismatchError,
    _parse_json_document,
    _require_bool,
    _require_int,
    _require_string,
    _safe_argument,
    _safe_environment,
    _validate_envelope,
    _verify_executable,
)

SESSION_HELPER_PATH = Path(
    "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-session"
)
SESSION_PROTOCOL_VERSION = 1
SESSION_SCHEMA_VERSION = 1
MAX_SESSION_FRAME_BYTES = 128 * 1024


class SessionBrokenError(KillSwitchClientError):
    """Raised when the authenticated privileged session unexpectedly ends."""


class SessionNotOpenError(KillSwitchClientError):
    """Raised when an operation is attempted before session authorization."""


class SessionTransport(Protocol):
    def start(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> Mapping[str, Any]:
        """Start the authenticated broker and return its ready frame."""

    def exchange(
        self,
        request: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        """Exchange one JSON request and response with the broker."""

    def close(self, *, timeout: float) -> None:
        """Close the broker process and all pipes."""


class JsonLineSessionTransport:
    """Persistent JSON-lines transport over one pkexec-authenticated process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self._lock = threading.Lock()

    def start(
        self,
        arguments: Sequence[str],
        *,
        timeout: float,
        environment: Mapping[str, str],
    ) -> Mapping[str, Any]:
        if self._process is not None:
            raise SessionBrokenError("Kill-switch helper session is already started.")
        try:
            process = subprocess.Popen(
                list(arguments),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=dict(environment),
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise PkexecUnavailableError(
                f"Could not execute the fixed pkexec binary: {arguments[0]}"
            ) from exc
        except OSError as exc:
            raise KillSwitchClientError(
                f"Could not start the kill-switch helper session: {exc}"
            ) from exc
        self._process = process
        try:
            return self._read_frame(timeout=timeout, starting=True)
        except Exception:
            self._terminate_process()
            raise

    def exchange(
        self,
        request: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        with self._lock:
            process = self._require_process()
            if process.stdin is None:
                raise SessionBrokenError("Kill-switch session input pipe is unavailable.")
            data = (
                json.dumps(dict(request), sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            if len(data) > MAX_SESSION_FRAME_BYTES:
                raise ValueError("Kill-switch session request exceeds the size limit.")
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise SessionBrokenError(
                    "Kill-switch helper session closed its input pipe."
                ) from exc
            try:
                return self._read_frame(timeout=timeout, starting=False)
            except HelperTimeoutError:
                self._terminate_process()
                raise

    def close(self, *, timeout: float) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=min(timeout, 3.0))
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()

    def _require_process(self) -> subprocess.Popen[bytes]:
        process = self._process
        if process is None:
            raise SessionNotOpenError("Kill-switch helper session is not open.")
        if process.poll() is not None:
            raise SessionBrokenError(
                f"Kill-switch helper session exited with status {process.returncode}."
            )
        return process

    def _read_frame(self, *, timeout: float, starting: bool) -> Mapping[str, Any]:
        process = self._process
        if process is None or process.stdout is None or process.stderr is None:
            raise SessionBrokenError("Kill-switch session output pipes are unavailable.")
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        try:
            while True:
                newline = self._stdout_buffer.find(b"\n")
                if newline >= 0:
                    raw = bytes(self._stdout_buffer[:newline])
                    del self._stdout_buffer[: newline + 1]
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise InvalidHelperResponseError(
                            "Kill-switch session returned non-UTF-8 output."
                        ) from exc
                    return _parse_json_document(text)

                if len(self._stdout_buffer) > MAX_SESSION_FRAME_BYTES:
                    raise InvalidHelperResponseError(
                        "Kill-switch session response exceeded the size limit."
                    )
                if len(self._stderr_buffer) > MAX_SESSION_FRAME_BYTES:
                    raise InvalidHelperResponseError(
                        "Kill-switch session error output exceeded the size limit."
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HelperTimeoutError(
                        f"Kill-switch helper session timed out after {timeout:g} seconds."
                    )
                events = selector.select(remaining)
                if not events:
                    raise HelperTimeoutError(
                        f"Kill-switch helper session timed out after {timeout:g} seconds."
                    )
                for key, _ in events:
                    try:
                        chunk = os.read(key.fileobj.fileno(), 4096)
                    except OSError as exc:
                        raise SessionBrokenError(
                            "Could not read from the kill-switch session."
                        ) from exc
                    if chunk:
                        if key.data == "stdout":
                            self._stdout_buffer.extend(chunk)
                        else:
                            self._stderr_buffer.extend(chunk)
                    else:
                        try:
                            selector.unregister(key.fileobj)
                        except Exception:
                            pass

                returncode = process.poll()
                if returncode is not None and b"\n" not in self._stdout_buffer:
                    stderr_text = self._stderr_buffer.decode("utf-8", errors="replace").strip()
                    if starting and returncode in {126, 127}:
                        try:
                            _parse_json_document(stderr_text)
                        except InvalidHelperResponseError:
                            raise AuthorizationDeniedError(
                                "Polkit authorization was cancelled or denied."
                            )
                    if stderr_text:
                        try:
                            payload = _parse_json_document(stderr_text)
                        except InvalidHelperResponseError:
                            payload = None
                        if isinstance(payload, dict) and payload.get("ok") is False:
                            raise HelperCommandError(
                                action=str(payload.get("action") or "session-start"),
                                kind=str(payload.get("error") or "session-start"),
                                message=str(payload.get("message") or "Session start failed."),
                                returncode=returncode,
                                payload=payload,
                            )
                    raise SessionBrokenError(
                        f"Kill-switch helper session exited with status {returncode}."
                    )
        finally:
            selector.close()

    def _terminate_process(self) -> None:
        try:
            self.close(timeout=1.0)
        except Exception:
            self._process = None


@dataclass(frozen=True, slots=True)
class SessionReady:
    session_pid: int
    max_requests: int
    idle_timeout_seconds: int
    payload: Mapping[str, Any]


class KillSwitchSessionClient:
    """One-authentication session client for multiple restricted helper actions."""

    def __init__(
        self,
        *,
        session_path: Path = SESSION_HELPER_PATH,
        pkexec_path: Path = PKEXEC_PATH,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: SessionTransport | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if timeout <= 0 or timeout > 300:
            raise ValueError("Session timeout must be greater than 0 and at most 300 seconds.")
        self.session_path = session_path
        self.pkexec_path = pkexec_path
        self.timeout = float(timeout)
        self.transport = transport if transport is not None else JsonLineSessionTransport()
        self.environment = dict(os.environ if environment is None else environment)
        self._ready: SessionReady | None = None
        self._request_id = 0
        self._request_lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._ready is not None

    @property
    def session_pid(self) -> int | None:
        return None if self._ready is None else self._ready.session_pid

    def open(self) -> SessionReady:
        if self._ready is not None:
            return self._ready
        self._preflight()
        frame = self.transport.start(
            [
                str(self.pkexec_path),
                "--disable-internal-agent",
                str(self.session_path),
            ],
            timeout=self.timeout,
            environment=_safe_environment(self.environment),
        )
        ready = self._validate_ready(frame)
        self._ready = ready
        self._request_id = 0
        return ready

    def status(self) -> KillSwitchStatus:
        return self._status_action("status", {})

    def enable(
        self,
        *,
        interfaces: Sequence[str],
        endpoints: Sequence[str],
    ) -> KillSwitchStatus:
        return self._status_action(
            "enable",
            {
                "interfaces": _safe_values(interfaces, "interfaces"),
                "endpoints": _safe_values(endpoints, "endpoints"),
            },
        )

    def set_interfaces(self, interfaces: Sequence[str]) -> KillSwitchStatus:
        return self._status_action(
            "set-interfaces",
            {"interfaces": _safe_values(interfaces, "interfaces")},
        )

    def set_endpoints(self, endpoints: Sequence[str]) -> KillSwitchStatus:
        return self._status_action(
            "set-endpoints",
            {"endpoints": _safe_values(endpoints, "endpoints")},
        )

    def add_endpoint(self, endpoint: str) -> KillSwitchStatus:
        return self._status_action(
            "add-endpoint", {"endpoint": _safe_argument(endpoint)}
        )

    def remove_endpoint(self, endpoint: str) -> KillSwitchStatus:
        return self._status_action(
            "remove-endpoint", {"endpoint": _safe_argument(endpoint)}
        )

    def disable(self) -> KillSwitchStatus:
        return self._status_action("disable", {})

    def emergency_reset(self) -> KillSwitchStatus:
        return self._status_action("emergency-reset", {})

    def close(self) -> None:
        if self._ready is None:
            self.transport.close(timeout=self.timeout)
            return
        try:
            frame = self._exchange("close", {})
            payload = frame.get("payload")
            if not isinstance(payload, dict) or payload != {"ok": True, "action": "close"}:
                raise InvalidHelperResponseError(
                    "Kill-switch session returned an invalid close response."
                )
        finally:
            self._ready = None
            self.transport.close(timeout=self.timeout)

    def __enter__(self) -> "KillSwitchSessionClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _status_action(
        self,
        action: str,
        fields: Mapping[str, Any],
    ) -> KillSwitchStatus:
        frame = self._exchange(action, fields)
        returncode = _require_session_int(frame, "returncode")
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            raise InvalidHelperResponseError(
                "Kill-switch session payload must be a JSON object."
            )
        _validate_envelope(payload, expected_action=action)
        ok = _require_bool(payload, "ok")
        if returncode == 0 and not ok:
            raise InvalidHelperResponseError(
                "Session returned an error payload with a successful exit status."
            )
        if returncode != 0 and ok:
            raise InvalidHelperResponseError(
                "Session returned a success payload with a failing exit status."
            )
        if not ok:
            raise HelperCommandError(
                action=action,
                kind=_require_string(payload, "error"),
                message=_require_string(payload, "message"),
                returncode=returncode,
                payload=payload,
            )
        status = KillSwitchStatus.from_response(
            HelperResponse(action=action, returncode=returncode, payload=payload)
        )
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
                f"Action {action!r} returned state {status.state!r}, expected {expected_state!r}."
            )
        return status

    def _exchange(self, action: str, fields: Mapping[str, Any]) -> Mapping[str, Any]:
        ready = self._ready
        if ready is None:
            raise SessionNotOpenError(
                "Kill-switch helper session must be authorized before use."
            )
        with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
            request = {"request_id": request_id, "action": action, **dict(fields)}
            frame = self.transport.exchange(request, timeout=self.timeout)
        self._validate_frame(
            frame,
            request_id=request_id,
            session_pid=ready.session_pid,
        )
        return frame

    def _preflight(self) -> None:
        _verify_executable(
            self.pkexec_path,
            role="pkexec",
            error_type=PkexecUnavailableError,
            exact_mode=None,
        )
        _verify_executable(
            self.session_path,
            role="installed helper session",
            error_type=HelperNotInstalledError,
            exact_mode=0o755,
        )

    @staticmethod
    def _validate_ready(frame: Mapping[str, Any]) -> SessionReady:
        if not isinstance(frame, Mapping):
            raise InvalidHelperResponseError("Session ready frame must be an object.")
        if frame.get("event") != "ready":
            raise InvalidHelperResponseError("Session did not return a ready event.")
        if _require_session_int(frame, "session_protocol_version") != SESSION_PROTOCOL_VERSION:
            raise ProtocolMismatchError("Unsupported helper-session protocol version.")
        if _require_session_int(frame, "session_schema_version") != SESSION_SCHEMA_VERSION:
            raise ProtocolMismatchError("Unsupported helper-session schema version.")
        if _require_session_int(frame, "protocol_version") != EXPECTED_PROTOCOL_VERSION:
            raise ProtocolMismatchError("Session helper protocol does not match the application.")
        if _require_session_int(frame, "helper_stage") != EXPECTED_HELPER_STAGE:
            raise ProtocolMismatchError("Session helper stage does not match the application.")
        session_pid = _require_session_int(frame, "session_pid")
        max_requests = _require_session_int(frame, "max_requests")
        idle_timeout = _require_session_int(frame, "idle_timeout_seconds")
        if session_pid <= 1 or max_requests <= 0 or idle_timeout <= 0:
            raise InvalidHelperResponseError("Session ready frame contains invalid limits.")
        return SessionReady(
            session_pid=session_pid,
            max_requests=max_requests,
            idle_timeout_seconds=idle_timeout,
            payload=dict(frame),
        )

    @staticmethod
    def _validate_frame(
        frame: Mapping[str, Any],
        *,
        request_id: int,
        session_pid: int,
    ) -> None:
        if _require_session_int(frame, "session_protocol_version") != SESSION_PROTOCOL_VERSION:
            raise ProtocolMismatchError("Session response protocol version changed.")
        if _require_session_int(frame, "session_schema_version") != SESSION_SCHEMA_VERSION:
            raise ProtocolMismatchError("Session response schema version changed.")
        if _require_session_int(frame, "session_pid") != session_pid:
            raise InvalidHelperResponseError("Session response came from a different broker process.")
        if _require_session_int(frame, "request_id") != request_id:
            raise InvalidHelperResponseError("Session response request_id does not match the request.")
        _require_session_int(frame, "returncode")


def _safe_values(values: Sequence[str], field: str) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"Expected a sequence for {field}.")
    result = [_safe_argument(value) for value in values]
    if not result:
        raise ValueError(f"At least one value is required for {field}.")
    if len(result) > 32:
        raise ValueError(f"At most 32 values are allowed for {field}.")
    return result


def _require_session_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidHelperResponseError(f"Session field {key!r} must be an integer.")
    return value


__all__ = [
    "JsonLineSessionTransport",
    "KillSwitchSessionClient",
    "SESSION_HELPER_PATH",
    "SESSION_PROTOCOL_VERSION",
    "SESSION_SCHEMA_VERSION",
    "SessionBrokenError",
    "SessionNotOpenError",
    "SessionReady",
    "SessionTransport",
]
