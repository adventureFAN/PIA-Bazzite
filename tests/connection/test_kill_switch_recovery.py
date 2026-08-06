from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pia_bazzite.kill_switch_client import KillSwitchStatus
from pia_bazzite.kill_switch_recovery import (
    FirewallRoutePlan,
    KillSwitchRecoveryOrchestrator,
    PreparedServerSwitch,
    ProtectedReconnectError,
    ProtectedServerSwitchError,
    RecoveryPhase,
    UnsafeRecoveryPlanError,
)


OLD_UUID = "11111111-1111-4111-8111-111111111111"
NEW_UUID = "22222222-2222-4222-8222-222222222222"
OLD_ENDPOINT = "198.51.100.8:1337"
NEW_ENDPOINT = "203.0.113.9:1337"


def active_status(action: str = "status") -> KillSwitchStatus:
    return KillSwitchStatus(
        action=action,
        state="active",
        present=True,
        verified=True,
        table="pia_bazzite_killswitch",
        table_generation=1,
        capabilities=("status", "set-interfaces", "set-endpoints"),
        problems=(),
        payload={},
    )


def disabled_status(action: str = "status") -> KillSwitchStatus:
    return KillSwitchStatus(
        action=action,
        state="disabled",
        present=False,
        verified=True,
        table="pia_bazzite_killswitch",
        table_generation=1,
        capabilities=("status",),
        problems=(),
        payload={},
    )


class FakeSession:
    def __init__(self, timeline: list[str] | None = None) -> None:
        self.timeline = timeline if timeline is not None else []
        self.calls: list[object] = []
        self.status_value = active_status()
        self.open_error: BaseException | None = None
        self.status_error: BaseException | None = None
        self.interfaces_error: BaseException | None = None
        self.endpoints_error: BaseException | None = None

    def open(self) -> object:
        self.timeline.append("open")
        self.calls.append("open")
        if self.open_error is not None:
            raise self.open_error
        return object()

    def status(self) -> KillSwitchStatus:
        self.timeline.append("status")
        self.calls.append("status")
        if self.status_error is not None:
            raise self.status_error
        return self.status_value

    def set_interfaces(self, interfaces) -> KillSwitchStatus:
        values = tuple(interfaces)
        self.timeline.append("set_interfaces:" + ",".join(values))
        self.calls.append(("set_interfaces", values))
        if self.interfaces_error is not None:
            raise self.interfaces_error
        return active_status("set-interfaces")

    def set_endpoints(self, endpoints) -> KillSwitchStatus:
        values = tuple(endpoints)
        self.timeline.append("set_endpoints:" + ",".join(values))
        self.calls.append(("set_endpoints", values))
        if self.endpoints_error is not None:
            raise self.endpoints_error
        return active_status("set-endpoints")


class FakeBackend:
    def __init__(self, timeline: list[str] | None = None) -> None:
        self.timeline = timeline if timeline is not None else []
        self.calls: list[object] = []
        self.connected = False
        self.connect_result = NEW_UUID
        self.reconnect_result = OLD_UUID
        self.connect_error: BaseException | None = None
        self.reconnect_error: BaseException | None = None
        self.disconnect_error: BaseException | None = None
        self.state_error: BaseException | None = None

    def connect(self, config_path: Path) -> str:
        self.timeline.append("connect")
        self.calls.append(("connect", config_path))
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        return self.connect_result

    def reconnect(self, profile_uuid: str) -> str:
        self.timeline.append("reconnect")
        self.calls.append(("reconnect", profile_uuid))
        if self.reconnect_error is not None:
            raise self.reconnect_error
        self.connected = True
        return self.reconnect_result

    def is_connected(self) -> bool:
        self.timeline.append("is_connected")
        self.calls.append("is_connected")
        if self.state_error is not None:
            raise self.state_error
        return self.connected

    def disconnect(self, profile_uuid: str = "") -> None:
        self.timeline.append("disconnect")
        self.calls.append(("disconnect", profile_uuid))
        if self.disconnect_error is not None:
            raise self.disconnect_error
        self.connected = False


class RecoveryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "piabazzite.conf"
        self.config_path.write_text(
            "[Interface]\nPrivateKey = test\n\n"
            f"[Peer]\nEndpoint = {NEW_ENDPOINT}\n",
            encoding="utf-8",
        )
        self.config_path.chmod(0o600)
        self.old_route = FirewallRoutePlan.create(
            physical_interfaces=("wlan0",),
            endpoints=(OLD_ENDPOINT,),
        )
        self.reconnect_route = FirewallRoutePlan.create(
            physical_interfaces=("wlan0",),
            endpoints=(OLD_ENDPOINT,),
        )
        self.candidate = PreparedServerSwitch.create(config_path=self.config_path)

    def build(self, *, timeline=None, sink=None):
        session = FakeSession(timeline)
        backend = FakeBackend(timeline)
        orchestrator = KillSwitchRecoveryOrchestrator(
            session=session,
            vpn_backend=backend,
            event_sink=sink,
        )
        return orchestrator, session, backend


class RecoveryPlanTests(RecoveryTestCase):
    def test_route_plan_normalizes_and_rejects_unsafe_values(self) -> None:
        plan = FirewallRoutePlan.create(
            physical_interfaces=("wlan0", "eth0", "wlan0"),
            endpoints=("198.51.100.8:01337", OLD_ENDPOINT),
        )
        self.assertEqual(plan.physical_interfaces, ("eth0", "wlan0"))
        self.assertEqual(plan.endpoints, (OLD_ENDPOINT,))
        for interfaces, endpoints in (
            (("lo",), (OLD_ENDPOINT,)),
            (("wlan0;reboot",), (OLD_ENDPOINT,)),
            (("wlan0",), ("vpn.example:1337",)),
        ):
            with self.subTest(interfaces=interfaces, endpoints=endpoints):
                with self.assertRaises(UnsafeRecoveryPlanError):
                    FirewallRoutePlan.create(
                        physical_interfaces=interfaces,
                        endpoints=endpoints,
                    )

    def test_prepared_candidate_detects_later_config_change(self) -> None:
        self.config_path.write_text(
            "[Peer]\nEndpoint = 203.0.113.10:1337\n",
            encoding="utf-8",
        )
        with self.assertRaises(UnsafeRecoveryPlanError):
            self.candidate.verify()

    def test_invalid_profile_uuid_is_rejected_before_session_or_network(self) -> None:
        orchestrator, session, backend = self.build()
        with self.assertRaises(UnsafeRecoveryPlanError):
            orchestrator.reconnect(
                profile_uuid="profile; reboot",
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: True,
            )
        self.assertEqual(session.calls, [])
        self.assertEqual(backend.calls, [])


class ProtectedReconnectTests(RecoveryTestCase):
    def test_reconnect_verifies_lock_block_and_route_before_networkmanager(self) -> None:
        timeline: list[str] = []
        orchestrator, _, backend = self.build(timeline=timeline)
        result = orchestrator.reconnect(
            profile_uuid=OLD_UUID,
            route_plan=self.reconnect_route,
            blocked_path_probe=lambda: (timeline.append("probe"), True)[1],
        )
        self.assertEqual(result.profile_uuid, OLD_UUID)
        self.assertTrue(result.firewall_status.protection_active)
        self.assertEqual(
            timeline,
            [
                "open",
                "status",
                "is_connected",
                "probe",
                "set_interfaces:wlan0",
                f"set_endpoints:{OLD_ENDPOINT}",
                "status",
                "reconnect",
                "is_connected",
                "status",
            ],
        )
        self.assertNotIn(("disconnect", OLD_UUID), backend.calls)

    def test_unverified_lock_refuses_reconnect(self) -> None:
        orchestrator, session, backend = self.build()
        session.status_value = disabled_status()
        with self.assertRaises(ProtectedReconnectError):
            orchestrator.reconnect(
                profile_uuid=OLD_UUID,
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: True,
            )
        self.assertFalse(any(call[0] == "reconnect" for call in backend.calls if isinstance(call, tuple)))

    def test_still_connected_vpn_refuses_reconnect(self) -> None:
        orchestrator, _, backend = self.build()
        backend.connected = True
        with self.assertRaises(ProtectedReconnectError):
            orchestrator.reconnect(
                profile_uuid=OLD_UUID,
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: True,
            )
        self.assertNotIn(("reconnect", OLD_UUID), backend.calls)

    def test_failed_block_probe_never_changes_allowlists_or_reconnects(self) -> None:
        orchestrator, session, backend = self.build()
        with self.assertRaises(ProtectedReconnectError):
            orchestrator.reconnect(
                profile_uuid=OLD_UUID,
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: False,
            )
        self.assertFalse(any(isinstance(call, tuple) and call[0].startswith("set_") for call in session.calls))
        self.assertNotIn(("reconnect", OLD_UUID), backend.calls)

    def test_firewall_retarget_failure_never_reconnects_or_disables(self) -> None:
        orchestrator, session, backend = self.build()
        session.endpoints_error = RuntimeError("nft failed")
        with self.assertRaises(ProtectedReconnectError) as raised:
            orchestrator.reconnect(
                profile_uuid=OLD_UUID,
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: True,
            )
        self.assertTrue(raised.exception.firewall_retained)
        self.assertNotIn(("reconnect", OLD_UUID), backend.calls)
        self.assertFalse(any(call == "disable" for call in session.calls))

    def test_reconnect_failure_stays_fail_closed(self) -> None:
        orchestrator, session, backend = self.build()
        backend.reconnect_error = RuntimeError("nmcli up failed")
        with self.assertRaises(ProtectedReconnectError) as raised:
            orchestrator.reconnect(
                profile_uuid=OLD_UUID,
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: True,
            )
        self.assertTrue(raised.exception.firewall_retained)
        self.assertFalse(any(call == "disable" for call in session.calls))

    def test_postcheck_failure_stops_unverified_vpn_but_keeps_lock(self) -> None:
        orchestrator, session, backend = self.build()
        original_status = session.status
        count = 0

        def status_sequence():
            nonlocal count
            count += 1
            if count == 3:
                return disabled_status()
            return original_status()

        session.status = status_sequence  # type: ignore[method-assign]
        with self.assertRaises(ProtectedReconnectError):
            orchestrator.reconnect(
                profile_uuid=OLD_UUID,
                route_plan=self.reconnect_route,
                blocked_path_probe=lambda: True,
            )
        self.assertIn(("disconnect", OLD_UUID), backend.calls)
        self.assertFalse(any(call == "disable" for call in session.calls))


class ProtectedServerSwitchTests(RecoveryTestCase):
    def test_switch_is_offline_and_blocked_before_new_endpoint_is_admitted(self) -> None:
        timeline: list[str] = []
        orchestrator, _, backend = self.build(timeline=timeline)
        backend.connected = True
        result = orchestrator.switch_server(
            current_profile_uuid=OLD_UUID,
            current_route_plan=self.old_route,
            candidate=self.candidate,
            blocked_path_probe=lambda: (timeline.append("probe"), True)[1],
            physical_interface_resolver=lambda endpoint: (
                timeline.append("resolve:" + endpoint),
                "eth0",
            )[1],
        )
        self.assertEqual(result.profile_uuid, NEW_UUID)
        self.assertEqual(result.connection_plan.physical_interfaces, ("eth0",))
        self.assertEqual(
            timeline,
            [
                "open",
                "status",
                "is_connected",
                "disconnect",
                "is_connected",
                "probe",
                f"resolve:{NEW_ENDPOINT}",
                "set_interfaces:eth0,wlan0",
                f"set_endpoints:{OLD_ENDPOINT},{NEW_ENDPOINT}",
                f"set_endpoints:{NEW_ENDPOINT}",
                "set_interfaces:eth0",
                "status",
                "connect",
                "is_connected",
                "status",
            ],
        )

    def test_same_endpoint_is_refused_before_old_vpn_is_touched(self) -> None:
        same_config = Path(self.temp.name) / "same" / "piabazzite.conf"
        same_config.parent.mkdir()
        same_config.write_text(f"[Peer]\nEndpoint = {OLD_ENDPOINT}\n", encoding="utf-8")
        same_config.chmod(0o600)
        candidate = PreparedServerSwitch.create(config_path=same_config)
        orchestrator, session, backend = self.build()
        backend.connected = True
        with self.assertRaises(ProtectedServerSwitchError) as raised:
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=candidate,
                blocked_path_probe=lambda: True,
                physical_interface_resolver=lambda endpoint: "wlan0",
            )
        self.assertFalse(raised.exception.old_vpn_disconnected)
        self.assertEqual(session.calls, [])
        self.assertEqual(backend.calls, [])

    def test_unverified_lock_never_stops_old_vpn(self) -> None:
        orchestrator, session, backend = self.build()
        session.status_value = disabled_status()
        backend.connected = True
        with self.assertRaises(ProtectedServerSwitchError) as raised:
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=self.candidate,
                blocked_path_probe=lambda: True,
                physical_interface_resolver=lambda endpoint: "wlan0",
            )
        self.assertFalse(raised.exception.old_vpn_disconnected)
        self.assertNotIn(("disconnect", OLD_UUID), backend.calls)

    def test_old_disconnect_failure_never_retargets_firewall(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = True
        backend.disconnect_error = RuntimeError("nm down failed")
        with self.assertRaises(ProtectedServerSwitchError) as raised:
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=self.candidate,
                blocked_path_probe=lambda: True,
                physical_interface_resolver=lambda endpoint: "wlan0",
            )
        self.assertFalse(raised.exception.old_vpn_disconnected)
        self.assertFalse(any(isinstance(call, tuple) and call[0].startswith("set_") for call in session.calls))

    def test_failed_block_probe_keeps_old_endpoint_and_never_starts_new_vpn(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = True
        with self.assertRaises(ProtectedServerSwitchError) as raised:
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=self.candidate,
                blocked_path_probe=lambda: False,
                physical_interface_resolver=lambda endpoint: "wlan0",
            )
        self.assertTrue(raised.exception.old_vpn_disconnected)
        self.assertFalse(any(isinstance(call, tuple) and call[0].startswith("set_") for call in session.calls))
        self.assertFalse(any(isinstance(call, tuple) and call[0] == "connect" for call in backend.calls))

    def test_route_resolution_failure_is_fail_closed(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = True
        with self.assertRaises(ProtectedServerSwitchError) as raised:
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=self.candidate,
                blocked_path_probe=lambda: True,
                physical_interface_resolver=lambda endpoint: (_ for _ in ()).throw(RuntimeError("no route")),
            )
        self.assertTrue(raised.exception.old_vpn_disconnected)
        self.assertFalse(any(call == "disable" for call in session.calls))
        self.assertFalse(any(isinstance(call, tuple) and call[0] == "connect" for call in backend.calls))

    def test_new_connect_failure_retains_exact_new_firewall_route(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = True
        backend.connect_error = RuntimeError("new profile failed")
        with self.assertRaises(ProtectedServerSwitchError) as raised:
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=self.candidate,
                blocked_path_probe=lambda: True,
                physical_interface_resolver=lambda endpoint: "eth0",
            )
        self.assertTrue(raised.exception.old_vpn_disconnected)
        self.assertTrue(raised.exception.firewall_retained)
        self.assertIn(("set_endpoints", (NEW_ENDPOINT,)), session.calls)
        self.assertIn(("set_interfaces", ("eth0",)), session.calls)
        self.assertFalse(any(call == "disable" for call in session.calls))

    def test_postcheck_failure_stops_new_vpn_without_unlocking(self) -> None:
        orchestrator, session, backend = self.build()
        backend.connected = True
        original_status = session.status
        count = 0

        def status_sequence():
            nonlocal count
            count += 1
            if count == 3:
                return disabled_status()
            return original_status()

        session.status = status_sequence  # type: ignore[method-assign]
        with self.assertRaises(ProtectedServerSwitchError):
            orchestrator.switch_server(
                current_profile_uuid=OLD_UUID,
                current_route_plan=self.old_route,
                candidate=self.candidate,
                blocked_path_probe=lambda: True,
                physical_interface_resolver=lambda endpoint: "eth0",
            )
        self.assertIn(("disconnect", NEW_UUID), backend.calls)
        self.assertFalse(any(call == "disable" for call in session.calls))

    def test_events_document_fail_closed_switch_order(self) -> None:
        events = []
        orchestrator, _, backend = self.build(sink=events.append)
        backend.connected = True
        orchestrator.switch_server(
            current_profile_uuid=OLD_UUID,
            current_route_plan=self.old_route,
            candidate=self.candidate,
            blocked_path_probe=lambda: True,
            physical_interface_resolver=lambda endpoint: "eth0",
        )
        self.assertEqual(
            [event.phase for event in events],
            [
                RecoveryPhase.SWITCH_PREFLIGHT_STARTED,
                RecoveryPhase.SWITCH_PREFLIGHT_VERIFIED,
                RecoveryPhase.OLD_VPN_STOPPING,
                RecoveryPhase.OLD_VPN_STOPPED,
                RecoveryPhase.BLOCKED_PATH_CHECK_STARTED,
                RecoveryPhase.BLOCKED_PATH_VERIFIED,
                RecoveryPhase.NEW_ROUTE_RESOLVING,
                RecoveryPhase.NEW_ROUTE_RESOLVED,
                RecoveryPhase.FIREWALL_RETARGET_STARTED,
                RecoveryPhase.FIREWALL_RETARGETED,
                RecoveryPhase.NEW_VPN_STARTING,
                RecoveryPhase.NEW_VPN_STARTED,
                RecoveryPhase.POSTCHECK_STARTED,
                RecoveryPhase.SWITCH_VERIFIED,
            ],
        )


if __name__ == "__main__":
    unittest.main()
