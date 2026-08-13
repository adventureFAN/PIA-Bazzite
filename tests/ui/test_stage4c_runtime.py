from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pia_bazzite.kill_switch_runtime import (
    KILL_SWITCH_ENABLED_KEY,
    KillSwitchRuntimeController,
)
from pia_bazzite.kill_switch_session import KillSwitchSessionClient
from pia_bazzite.kill_switch_state import KillSwitchMode


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
RUNTIME = ROOT / "pia_bazzite" / "kill_switch_runtime.py"
PREVIEW = ROOT / "tools" / "pia-bazzite-stage4c-runtime-preview.py"


class FakeSettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def value(self, key, default=None, *, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return bool(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        return None


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
            "inspect-route",
            "set-interfaces",
            "set-endpoints",
            "add-endpoint",
            "remove-endpoint",
        ],
        "problems": [],
        "physical_interfaces": ["wlo1"] if present else [],
        "endpoints": ["198.51.100.1:1337"] if present else [],
    }


class FakeSessionTransport:
    def __init__(self, *, state: str = "active") -> None:
        self.state = state
        self.session_pid = 4815
        self.starts = 0
        self.requests = 0
        self.alive = False

    def start(self, arguments, *, timeout, environment):
        self.starts += 1
        self.alive = True
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
        self.requests += 1
        action = str(request["action"])
        payload = (
            {"ok": True, "action": "close"}
            if action == "close"
            else status_payload(action, self.state)
        )
        return {
            "session_protocol_version": 1,
            "session_schema_version": 1,
            "session_pid": self.session_pid,
            "request_id": request["request_id"],
            "returncode": 0,
            "payload": payload,
        }

    def is_alive(self):
        return self.alive

    def close(self, *, timeout):
        self.alive = False
        return None


class RuntimeControllerTests(unittest.TestCase):
    def make_settings(self):
        return tempfile.TemporaryDirectory(), FakeSettings()

    def test_disabled_feature_never_calls_privileged_status_reader(self) -> None:
        temporary, settings = self.make_settings()
        calls = 0

        def reader():
            nonlocal calls
            calls += 1
            raise AssertionError("disabled kill switch must not contact helper")

        with temporary:
            controller = KillSwitchRuntimeController(
                settings,
                status_reader=reader,
            )
            disconnected = controller.view_state(vpn_connected=False)
            connected = controller.view_state(vpn_connected=True)

        self.assertEqual(calls, 0)
        self.assertIs(disconnected.mode, KillSwitchMode.READY)
        self.assertIs(connected.mode, KillSwitchMode.VPN_ONLY)

    def test_enabled_feature_without_session_fails_closed_in_ui(self) -> None:
        temporary, settings = self.make_settings()
        with temporary:
            settings.setValue(KILL_SWITCH_ENABLED_KEY, True)
            controller = KillSwitchRuntimeController(settings)
            state = controller.view_state(vpn_connected=True)
        self.assertIs(state.mode, KillSwitchMode.ERROR)
        self.assertTrue(state.diagnostic)

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_real_session_client_status_drives_green_runtime_state(
        self,
        lstat,
        is_symlink,
    ) -> None:
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1

        lstat.return_value = Meta()
        transport = FakeSessionTransport(state="active")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pkexec = root / "pkexec"
            session = root / "session"
            pkexec.write_text("pkexec", encoding="utf-8")
            session.write_text("session", encoding="utf-8")
            pkexec.chmod(0o755)
            session.chmod(0o755)
            settings = FakeSettings()
            settings.setValue(KILL_SWITCH_ENABLED_KEY, True)
            client = KillSwitchSessionClient(
                pkexec_path=pkexec,
                session_path=session,
                transport=transport,
            )
            client.open()
            controller = KillSwitchRuntimeController(
                settings,
                status_reader=client.status,
            )
            state = controller.view_state(vpn_connected=True)
            client.close()

        self.assertIs(state.mode, KillSwitchMode.ACTIVE)
        self.assertTrue(state.protection_guaranteed)
        self.assertEqual(transport.starts, 1)
        self.assertEqual(transport.requests, 2)  # status plus explicit close

    @patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False)
    @patch("pia_bazzite.kill_switch_client.Path.lstat")
    def test_real_session_client_disabled_status_drives_armed_state(
        self,
        lstat,
        is_symlink,
    ) -> None:
        class Meta:
            st_mode = 0o100755
            st_uid = 0
            st_gid = 0
            st_nlink = 1

        lstat.return_value = Meta()
        transport = FakeSessionTransport(state="disabled")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pkexec = root / "pkexec"
            session = root / "session"
            pkexec.write_text("pkexec", encoding="utf-8")
            session.write_text("session", encoding="utf-8")
            pkexec.chmod(0o755)
            session.chmod(0o755)
            settings = FakeSettings()
            settings.setValue(KILL_SWITCH_ENABLED_KEY, True)
            client = KillSwitchSessionClient(
                pkexec_path=pkexec,
                session_path=session,
                transport=transport,
            )
            client.open()
            controller = KillSwitchRuntimeController(
                settings,
                status_reader=client.status,
            )
            state = controller.view_state(vpn_connected=False)
            client.close()

        self.assertIs(state.mode, KillSwitchMode.ARMED)
        self.assertFalse(state.firewall_active)


class Stage4CRuntimeStaticTests(unittest.TestCase):
    def test_main_window_uses_runtime_controller_for_real_status_updates(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.kill_switch_runtime = KillSwitchRuntimeController", source)
        self.assertIn("self.kill_switch_runtime.view_state", source)
        self.assertIn("self._apply_kill_switch_view_state", source)
        self.assertIn("kill_switch_status_reader: Callable[[], Any] | None = None", source)

    def test_optional_mode_does_not_probe_helper_when_disabled(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        disabled_branch = source.index("if not enabled:")
        reader_branch = source.index("if self.status_reader is None:")
        self.assertLess(disabled_branch, reader_branch)

    def test_tray_uses_same_runtime_state_as_main_window(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("status_action = QAction(tr(state.tray_status_key), menu)", source)
        self.assertIn("self.tray.setIcon(status_icon(state.icon_state))", source)
        self.assertNotIn("status_action.setIcon(status_dot_icon", source)
        self.assertIn("self.tray.setToolTip(tr(state.tray_tooltip_key))", source)

    def test_runtime_preview_is_network_and_privilege_free(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("stage4_preview=True", source)
        self.assertNotIn("network_manager.", source)
        self.assertNotIn("pkexec", source)
        self.assertNotIn("nft ", source)


if __name__ == "__main__":
    unittest.main()
