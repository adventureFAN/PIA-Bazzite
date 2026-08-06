from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pia_bazzite.kill_switch_client import (
    AuthorizationDeniedError,
    InvalidHelperResponseError,
)
from pia_bazzite.kill_switch_session import (
    KillSwitchSessionClient,
    SessionNotOpenError,
)


def status_payload(action: str, state: str = "active") -> dict[str, object]:
    present = state == "active"
    return {
        "ok": True,
        "schema_version": 1,
        "protocol_version": 1,
        "helper_stage": 5,
        "action": action,
        "state": state,
        "present": present,
        "verified": True,
        "table": "pia_bazzite_killswitch",
        "table_generation": 1,
        "capabilities": [
            "set-interfaces",
            "set-endpoints",
            "add-endpoint",
            "remove-endpoint",
        ],
        "problems": [],
    }


class FakeTransport:
    def __init__(self) -> None:
        self.starts: list[tuple[list[str], float, dict[str, str]]] = []
        self.requests: list[dict[str, object]] = []
        self.closed = 0
        self.session_pid = 4242
        self.start_error: Exception | None = None

    def start(self, arguments, *, timeout, environment):
        self.starts.append((list(arguments), timeout, dict(environment)))
        if self.start_error is not None:
            raise self.start_error
        return {
            "event": "ready",
            "session_protocol_version": 1,
            "session_schema_version": 1,
            "protocol_version": 1,
            "helper_stage": 5,
            "session_pid": self.session_pid,
            "max_requests": 128,
            "idle_timeout_seconds": 300,
        }

    def exchange(self, request, *, timeout):
        document = dict(request)
        self.requests.append(document)
        action = str(document["action"])
        if action == "close":
            payload = {"ok": True, "action": "close"}
        else:
            state = "disabled" if action in {"disable", "emergency-reset"} else "active"
            payload = status_payload(action, state)
        return {
            "session_protocol_version": 1,
            "session_schema_version": 1,
            "session_pid": self.session_pid,
            "request_id": document["request_id"],
            "returncode": 0,
            "payload": payload,
        }

    def close(self, *, timeout):
        self.closed += 1


class KillSwitchSessionClientTests(unittest.TestCase):
    def make_client(self, transport: FakeTransport):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        pkexec = root / "pkexec"
        session = root / "session"
        pkexec.write_text("pkexec", encoding="utf-8")
        session.write_text("session", encoding="utf-8")
        pkexec.chmod(0o755)
        session.chmod(0o755)
        client = KillSwitchSessionClient(
            pkexec_path=pkexec,
            session_path=session,
            transport=transport,
            environment={"DISPLAY": ":1", "LD_PRELOAD": "/tmp/evil.so"},
        )
        return temporary, client

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_one_pkexec_start_serves_multiple_actions(self, lstat, is_symlink):
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1
        lstat.return_value = Meta()
        transport = FakeTransport()
        temporary, client = self.make_client(transport)
        with temporary:
            ready = client.open()
            enabled = client.enable(
                interfaces=("wan0",),
                endpoints=("198.51.100.10:1337",),
            )
            status = client.status()
            updated = client.set_interfaces(("lan0",))
            disabled = client.disable()
            client.close()
        self.assertEqual(ready.session_pid, 4242)
        self.assertTrue(enabled.protection_active)
        self.assertTrue(status.protection_active)
        self.assertTrue(updated.protection_active)
        self.assertFalse(disabled.protection_active)
        self.assertEqual(len(transport.starts), 1)
        self.assertEqual([request["request_id"] for request in transport.requests], [1, 2, 3, 4, 5])
        self.assertEqual(transport.closed, 1)
        argv, _, environment = transport.starts[0]
        self.assertEqual(argv[1], "--disable-internal-agent")
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertEqual(environment["DISPLAY"], ":1")

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_authorization_denial_occurs_only_during_open(self, lstat, is_symlink):
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1
        lstat.return_value = Meta()
        transport = FakeTransport()
        transport.start_error = AuthorizationDeniedError("denied")
        temporary, client = self.make_client(transport)
        with temporary, self.assertRaises(AuthorizationDeniedError):
            client.open()
        self.assertEqual(len(transport.starts), 1)
        self.assertEqual(transport.requests, [])

    def test_operations_require_an_open_session(self):
        client = KillSwitchSessionClient(transport=FakeTransport())
        with self.assertRaises(SessionNotOpenError):
            client.status()

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_argument_validation_happens_before_exchange(self, lstat, is_symlink):
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1
        lstat.return_value = Meta()
        transport = FakeTransport()
        temporary, client = self.make_client(transport)
        with temporary:
            client.open()
            with self.assertRaises(ValueError):
                client.set_interfaces((" bad ",))
        self.assertEqual(transport.requests, [])

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_response_must_come_from_same_broker_pid(self, lstat, is_symlink):
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1
        lstat.return_value = Meta()
        transport = FakeTransport()
        original = transport.exchange
        def wrong_pid(request, *, timeout):
            frame = dict(original(request, timeout=timeout))
            frame["session_pid"] = 9999
            return frame
        transport.exchange = wrong_pid  # type: ignore[method-assign]
        temporary, client = self.make_client(transport)
        with temporary:
            client.open()
            with self.assertRaises(InvalidHelperResponseError):
                client.status()

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_open_is_idempotent_without_second_pkexec(self, lstat, is_symlink):
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1
        lstat.return_value = Meta()
        transport = FakeTransport()
        temporary, client = self.make_client(transport)
        with temporary:
            first = client.open()
            second = client.open()
        self.assertIs(first, second)
        self.assertEqual(len(transport.starts), 1)


if __name__ == "__main__":
    unittest.main()
