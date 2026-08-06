from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pia_bazzite.kill_switch_client import KillSwitchStatus
from pia_bazzite.kill_switch_connection import (
    ConnectionPhase,
    ConnectionPlan,
    IntentionalDisconnectError,
    KillSwitchConnectionOrchestrator,
    KillSwitchPreparationError,
    PostConnectVerificationError,
    ServerSwitchDeferredError,
    UnsafeConnectionPlanError,
    VpnStartError,
)


def helper_status(*, active: bool, action: str = "status") -> KillSwitchStatus:
    return KillSwitchStatus(
        action=action,
        state="active" if active else "disabled",
        present=active,
        verified=True,
        table="pia_bazzite_killswitch",
        table_generation=1,
        capabilities=("status", "enable"),
        problems=(),
        payload={},
    )


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.open_error: BaseException | None = None
        self.enable_error: BaseException | None = None
        self.status_error: BaseException | None = None
        self.disable_error: BaseException | None = None
        self.enable_status = helper_status(active=True, action="enable")
        self.status_value = helper_status(active=True)
        self.disable_status = helper_status(active=False, action="disable")

    def open(self) -> object:
        self.calls.append("open")
        if self.open_error is not None:
            raise self.open_error
        return object()

    def enable(self, *, interfaces, endpoints) -> KillSwitchStatus:
        self.calls.append(("enable", tuple(interfaces), tuple(endpoints)))
        if self.enable_error is not None:
            raise self.enable_error
        return self.enable_status

    def status(self) -> KillSwitchStatus:
        self.calls.append("status")
        if self.status_error is not None:
            raise self.status_error
        return self.status_value

    def disable(self) -> KillSwitchStatus:
        self.calls.append("disable")
        if self.disable_error is not None:
            raise self.disable_error
        return self.disable_status


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.connect_result = "profile-uuid"
        self.connected = True
        self.connect_error: BaseException | None = None
        self.state_error: BaseException | None = None
        self.disconnect_error: BaseException | None = None

    def connect(self, config_path: Path) -> str:
        self.calls.append(("connect", config_path))
        if self.connect_error is not None:
            raise self.connect_error
        return self.connect_result

    def is_connected(self) -> bool:
        self.calls.append("is_connected")
        if self.state_error is not None:
            raise self.state_error
        return self.connected

    def disconnect(self, profile_uuid: str = "") -> None:
        self.calls.append(("disconnect", profile_uuid))
        if self.disconnect_error is not None:
            raise self.disconnect_error


class ConnectionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "piabazzite.conf"
        self.config_path.write_text(
            "[Interface]\nPrivateKey = test\n\n"
            "[Peer]\nEndpoint = 198.51.100.8:1337\n",
            encoding="utf-8",
        )
        self.config_path.chmod(0o600)

    def plan(self, *, endpoints=("198.51.100.8:1337",)) -> ConnectionPlan:
        return ConnectionPlan.create(
            config_path=self.config_path,
            physical_interfaces=("wlan0",),
            endpoints=endpoints,
        )


class ConnectionPlanTests(ConnectionTestCase):
    def test_plan_normalizes_interfaces_and_endpoint(self) -> None:
        plan = ConnectionPlan.create(
            config_path=self.config_path,
            physical_interfaces=("wlan0", "eth0", "wlan0"),
            endpoints=("198.51.100.8:01337",),
        )
        self.assertEqual(plan.physical_interfaces, ("eth0", "wlan0"))
        self.assertEqual(plan.endpoints, ("198.51.100.8:1337",))

    def test_plan_rejects_hostnames_shell_text_and_special_interfaces(self) -> None:
        for interfaces, endpoints in (
            (("wlan0;reboot",), ("198.51.100.8:1337",)),
            (("lo",), ("198.51.100.8:1337",)),
            (("wlan0",), ("vpn.example:1337",)),
            (("wlan0",), ("127.0.0.1:1337",)),
        ):
            with self.subTest(interfaces=interfaces, endpoints=endpoints):
                with self.assertRaises(UnsafeConnectionPlanError):
                    ConnectionPlan.create(
                        config_path=self.config_path,
                        physical_interfaces=interfaces,
                        endpoints=endpoints,
                    )

    def test_stage5a_requires_exactly_one_endpoint(self) -> None:
        with self.assertRaises(UnsafeConnectionPlanError):
            ConnectionPlan.create(
                config_path=self.config_path,
                physical_interfaces=("wlan0",),
                endpoints=("198.51.100.8:1337", "198.51.100.9:1337"),
            )

    def test_config_endpoint_must_match_firewall_allowlist(self) -> None:
        plan = self.plan(endpoints=("198.51.100.9:1337",))
        with self.assertRaises(UnsafeConnectionPlanError):
            plan.verify_config_file()

    def test_config_must_be_fixed_absolute_private_regular_file(self) -> None:
        with self.assertRaises(UnsafeConnectionPlanError):
            ConnectionPlan.create(
                config_path=Path("piabazzite.conf"),
                physical_interfaces=("wlan0",),
                endpoints=("198.51.100.8:1337",),
            )

        wrong = Path(self.temp.name) / "other.conf"
        wrong.write_text("test", encoding="utf-8")
        wrong.chmod(0o600)
        with self.assertRaises(UnsafeConnectionPlanError):
            ConnectionPlan.create(
                config_path=wrong,
                physical_interfaces=("wlan0",),
                endpoints=("198.51.100.8:1337",),
            )

        plan = self.plan()
        self.config_path.chmod(0o644)
        with self.assertRaises(UnsafeConnectionPlanError):
            plan.verify_config_file()


class OrchestratorTests(ConnectionTestCase):
    def build(self, *, sink=None):
        session = FakeSession()
        backend = FakeBackend()
        orchestrator = KillSwitchConnectionOrchestrator(
            session=session,
            vpn_backend=backend,
            event_sink=sink,
        )
        return orchestrator, session, backend

    def test_disabled_mode_bypasses_privileged_session(self) -> None:
        orchestrator, session, backend = self.build()
        result = orchestrator.connect(self.plan(), kill_switch_enabled=False)
        self.assertFalse(result.kill_switch_enabled)
        self.assertIsNone(result.firewall_status)
        self.assertEqual(session.calls, [])
        self.assertEqual(
            backend.calls,
            [("connect", self.config_path), "is_connected"],
        )

    def test_enabled_mode_prepares_firewall_before_vpn_and_postchecks(self) -> None:
        timeline: list[str] = []
        session = FakeSession()
        backend = FakeBackend()

        original_open = session.open
        original_enable = session.enable
        original_status = session.status
        original_connect = backend.connect
        original_state = backend.is_connected

        session.open = lambda: (timeline.append("open"), original_open())[1]  # type: ignore[method-assign]
        session.enable = lambda **kwargs: (timeline.append("enable"), original_enable(**kwargs))[1]  # type: ignore[method-assign]
        backend.connect = lambda path: (timeline.append("connect"), original_connect(path))[1]  # type: ignore[method-assign]
        backend.is_connected = lambda: (timeline.append("is_connected"), original_state())[1]  # type: ignore[method-assign]
        session.status = lambda: (timeline.append("status"), original_status())[1]  # type: ignore[method-assign]

        orchestrator = KillSwitchConnectionOrchestrator(
            session=session,
            vpn_backend=backend,
        )
        result = orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertTrue(result.firewall_status and result.firewall_status.protection_active)
        self.assertEqual(timeline, ["open", "enable", "connect", "is_connected", "status"])

    def test_authorization_failure_never_starts_vpn(self) -> None:
        orchestrator, session, backend = self.build()
        session.open_error = RuntimeError("cancelled")
        with self.assertRaises(KillSwitchPreparationError):
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertEqual(backend.calls, [])

    def test_firewall_failure_never_starts_vpn(self) -> None:
        orchestrator, session, backend = self.build()
        session.enable_error = RuntimeError("nft failed")
        with self.assertRaises(KillSwitchPreparationError):
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertEqual(backend.calls, [])

    def test_unverified_enable_result_never_starts_vpn(self) -> None:
        orchestrator, session, backend = self.build()
        session.enable_status = helper_status(active=False, action="enable")
        with self.assertRaises(KillSwitchPreparationError):
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertEqual(backend.calls, [])

    def test_vpn_start_failure_retains_firewall_and_never_disables_it(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connect_error = RuntimeError("nmcli failed")
        with self.assertRaises(VpnStartError) as raised:
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertTrue(raised.exception.firewall_retained)
        self.assertNotIn("disable", session.calls)

    def test_missing_profile_uuid_disconnects_and_retains_firewall(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connect_result = ""
        with self.assertRaises(PostConnectVerificationError) as raised:
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertTrue(raised.exception.firewall_retained)
        self.assertIn(("disconnect", ""), backend.calls)
        self.assertNotIn("disable", session.calls)

    def test_inactive_vpn_postcheck_disconnects_and_retains_firewall(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = False
        with self.assertRaises(PostConnectVerificationError):
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertIn(("disconnect", "profile-uuid"), backend.calls)
        self.assertNotIn("disable", session.calls)

    def test_firewall_postcheck_failure_disconnects_vpn_without_unlocking(self) -> None:
        orchestrator, session, backend = self.build()
        session.status_error = RuntimeError("status unavailable")
        with self.assertRaises(PostConnectVerificationError):
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertIn(("disconnect", "profile-uuid"), backend.calls)
        self.assertNotIn("disable", session.calls)

    def test_disconnect_failure_is_reported_but_firewall_is_still_retained(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = False
        backend.disconnect_error = RuntimeError("disconnect failed")
        with self.assertRaises(PostConnectVerificationError) as raised:
            orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertEqual(raised.exception.rollback_error, "disconnect failed")
        self.assertTrue(raised.exception.firewall_retained)
        self.assertNotIn("disable", session.calls)

    def test_stage5a_refuses_server_switch_before_any_action(self) -> None:
        orchestrator, session, backend = self.build()
        with self.assertRaises(ServerSwitchDeferredError):
            orchestrator.connect(
                self.plan(),
                kill_switch_enabled=True,
                vpn_connected_before=True,
            )
        self.assertEqual(session.calls, [])
        self.assertEqual(backend.calls, [])

    def test_invalid_plan_file_is_rejected_before_session_or_network(self) -> None:
        orchestrator, session, backend = self.build()
        plan = self.plan()
        self.config_path.unlink()
        with self.assertRaises(UnsafeConnectionPlanError):
            orchestrator.connect(plan, kill_switch_enabled=True)
        self.assertEqual(session.calls, [])
        self.assertEqual(backend.calls, [])

    def test_events_document_the_fail_closed_order(self) -> None:
        events = []
        orchestrator, _, _ = self.build(sink=events.append)
        orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertEqual(
            [event.phase for event in events],
            [
                ConnectionPhase.PLAN_VALIDATED,
                ConnectionPhase.AUTHORIZATION_STARTED,
                ConnectionPhase.SESSION_AUTHORIZED,
                ConnectionPhase.FIREWALL_PREPARED,
                ConnectionPhase.VPN_STARTING,
                ConnectionPhase.VPN_STARTED,
                ConnectionPhase.POSTCHECK_STARTED,
                ConnectionPhase.CONNECTION_VERIFIED,
            ],
        )

    def test_broken_event_sink_cannot_interrupt_safety_flow(self) -> None:
        def broken_sink(_event) -> None:
            raise RuntimeError("GUI log failed")

        orchestrator, session, backend = self.build(sink=broken_sink)
        result = orchestrator.connect(self.plan(), kill_switch_enabled=True)
        self.assertEqual(result.profile_uuid, "profile-uuid")
        self.assertIn("status", session.calls)
        self.assertIn("is_connected", backend.calls)

    def test_intentional_disconnect_without_kill_switch_bypasses_session(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = False
        result = orchestrator.disconnect_intentionally(
            profile_uuid="profile-uuid",
            kill_switch_enabled=False,
        )
        self.assertTrue(result.vpn_disconnected)
        self.assertFalse(result.kill_switch_enabled)
        self.assertEqual(session.calls, [])
        self.assertEqual(
            backend.calls,
            [("disconnect", "profile-uuid"), "is_connected"],
        )

    def test_intentional_disconnect_keeps_lock_until_vpn_and_probe_are_verified(self) -> None:
        timeline: list[str] = []
        session = FakeSession()
        backend = FakeBackend()
        backend.connected = False

        original_open = session.open
        original_status = session.status
        original_disable = session.disable
        original_disconnect = backend.disconnect
        original_state = backend.is_connected

        session.open = lambda: (timeline.append("open"), original_open())[1]  # type: ignore[method-assign]
        session.status = lambda: (timeline.append("status"), original_status())[1]  # type: ignore[method-assign]
        backend.disconnect = lambda uuid="": (timeline.append("disconnect"), original_disconnect(uuid))[1]  # type: ignore[method-assign]
        backend.is_connected = lambda: (timeline.append("is_connected"), original_state())[1]  # type: ignore[method-assign]
        session.disable = lambda: (timeline.append("disable"), original_disable())[1]  # type: ignore[method-assign]

        orchestrator = KillSwitchConnectionOrchestrator(
            session=session,
            vpn_backend=backend,
        )
        result = orchestrator.disconnect_intentionally(
            profile_uuid="profile-uuid",
            kill_switch_enabled=True,
            blocked_path_probe=lambda: (timeline.append("probe"), True)[1],
        )
        self.assertEqual(
            timeline,
            ["open", "status", "disconnect", "is_connected", "probe", "disable"],
        )
        self.assertTrue(result.firewall_status and result.firewall_status.state == "disabled")

    def test_unverified_firewall_refuses_disconnect_and_unlock(self) -> None:
        orchestrator, session, backend = self.build()
        session.status_value = helper_status(active=False)
        with self.assertRaises(IntentionalDisconnectError) as raised:
            orchestrator.disconnect_intentionally(
                profile_uuid="profile-uuid",
                kill_switch_enabled=True,
            )
        self.assertFalse(raised.exception.vpn_disconnected)
        self.assertTrue(raised.exception.firewall_retained)
        self.assertEqual(backend.calls, [])
        self.assertNotIn("disable", session.calls)

    def test_disconnect_failure_never_disables_firewall(self) -> None:
        orchestrator, session, backend = self.build()
        backend.disconnect_error = RuntimeError("nm down failed")
        with self.assertRaises(IntentionalDisconnectError) as raised:
            orchestrator.disconnect_intentionally(
                profile_uuid="profile-uuid",
                kill_switch_enabled=True,
            )
        self.assertFalse(raised.exception.vpn_disconnected)
        self.assertTrue(raised.exception.firewall_retained)
        self.assertNotIn("disable", session.calls)

    def test_still_connected_vpn_never_disables_firewall(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = True
        with self.assertRaises(IntentionalDisconnectError):
            orchestrator.disconnect_intentionally(
                profile_uuid="profile-uuid",
                kill_switch_enabled=True,
            )
        self.assertNotIn("disable", session.calls)

    def test_failed_blocked_path_probe_keeps_firewall_active(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = False
        with self.assertRaises(IntentionalDisconnectError) as raised:
            orchestrator.disconnect_intentionally(
                profile_uuid="profile-uuid",
                kill_switch_enabled=True,
                blocked_path_probe=lambda: False,
            )
        self.assertTrue(raised.exception.vpn_disconnected)
        self.assertTrue(raised.exception.firewall_retained)
        self.assertNotIn("disable", session.calls)

    def test_disable_failure_reports_vpn_down_and_retains_lock(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = False
        session.disable_error = RuntimeError("nft delete failed")
        with self.assertRaises(IntentionalDisconnectError) as raised:
            orchestrator.disconnect_intentionally(
                profile_uuid="profile-uuid",
                kill_switch_enabled=True,
                blocked_path_probe=lambda: True,
            )
        self.assertTrue(raised.exception.vpn_disconnected)
        self.assertTrue(raised.exception.firewall_retained)

    def test_disconnect_events_document_lock_before_unlock_order(self) -> None:
        events = []
        orchestrator, _, backend = self.build(sink=events.append)
        backend.connected = False
        orchestrator.disconnect_intentionally(
            profile_uuid="profile-uuid",
            kill_switch_enabled=True,
            blocked_path_probe=lambda: True,
        )
        self.assertEqual(
            [event.phase for event in events],
            [
                ConnectionPhase.DISCONNECT_PREFLIGHT_STARTED,
                ConnectionPhase.DISCONNECT_PREFLIGHT_VERIFIED,
                ConnectionPhase.VPN_STOPPING,
                ConnectionPhase.VPN_STOPPED,
                ConnectionPhase.BLOCKED_PATH_CHECK_STARTED,
                ConnectionPhase.BLOCKED_PATH_VERIFIED,
                ConnectionPhase.FIREWALL_RELEASING,
                ConnectionPhase.FIREWALL_RELEASED,
                ConnectionPhase.INTENTIONAL_DISCONNECT_VERIFIED,
            ],
        )


if __name__ == "__main__":
    unittest.main()
