from __future__ import annotations

from pathlib import Path
import unittest

from pia_bazzite.ipv6_guard_lifecycle import (
    IPv6GuardConnectError,
    IPv6GuardDisconnectError,
    IPv6GuardLifecycle,
    IPv6GuardStartupError,
    IPv6GuardStateError,
)
from pia_bazzite.kill_switch_client import HelperResponse, IPv6GuardStatus, KillSwitchStatus


PROFILE = "11111111-1111-4111-8111-111111111111"


def full_status(*, present: bool = False, verified: bool = True) -> KillSwitchStatus:
    state = "active" if present else "disabled"
    return KillSwitchStatus(
        action="status",
        state=state,
        present=present,
        verified=verified,
        table="pia_bazzite_killswitch",
        table_generation=1 if present else 0,
        capabilities=(),
        problems=() if verified else ("broken",),
        payload={},
    )


def guard_status(*, active: bool) -> IPv6GuardStatus:
    return IPv6GuardStatus.from_response(
        HelperResponse(
            action="ipv6-guard-status",
            returncode=0,
            payload={
                "ok": True,
                "schema_version": 1,
                "protocol_version": 1,
                "helper_stage": 5,
                "action": "ipv6-guard-status",
                "state": "active" if active else "disabled",
                "present": active,
                "verified": True,
                "table": "pia_bazzite_ipv6_guard",
                "table_generation": 1 if active else 0,
                "capabilities": ["ipv6-only-guard"],
                "problems": [],
            },
        )
    )


class FakeSession:
    def __init__(self, *, guard_active: bool = False, full_present: bool = False, events: list[str] | None = None) -> None:
        self.guard_active = guard_active
        self.full_present = full_present
        self.actions: list[str] = []
        self.events = events
        self.fail_disable = False

    def open(self):
        self.actions.append("open")
        if self.events is not None:
            self.events.append("session:open")
        return object()

    def status(self):
        self.actions.append("status")
        if self.events is not None:
            self.events.append("session:status")
        return full_status(present=self.full_present)

    def ipv6_guard_status(self):
        self.actions.append("guard-status")
        if self.events is not None:
            self.events.append("session:guard-status")
        return guard_status(active=self.guard_active)

    def ipv6_guard_enable(self):
        self.actions.append("guard-enable")
        if self.events is not None:
            self.events.append("session:guard-enable")
        self.guard_active = True
        return guard_status(active=True)

    def ipv6_guard_disable(self):
        self.actions.append("guard-disable")
        if self.events is not None:
            self.events.append("session:guard-disable")
        if self.fail_disable:
            raise RuntimeError("disable failed")
        self.guard_active = False
        return guard_status(active=False)


class FakeVpn:
    def __init__(self, *, connected: bool = False, events: list[str] | None = None) -> None:
        self.connected = connected
        self.actions: list[str] = []
        self.events = events
        self.fail_connect = False
        self.fail_disconnect = False
        self.unknown_state = False

    def connect(self, config_path: Path) -> str:
        self.actions.append("connect")
        if self.events is not None:
            self.events.append("vpn:connect")
        if self.fail_connect:
            raise RuntimeError("connect failed")
        self.connected = True
        return PROFILE

    def disconnect(self, profile_uuid: str = "") -> None:
        self.actions.append("disconnect")
        if self.events is not None:
            self.events.append("vpn:disconnect")
        if self.fail_disconnect:
            raise RuntimeError("disconnect failed")
        self.connected = False

    def is_connected(self) -> bool:
        self.actions.append("is-connected")
        if self.events is not None:
            self.events.append("vpn:is-connected")
        if self.unknown_state:
            raise RuntimeError("state unknown")
        return self.connected


class IPv6GuardLifecycleTests(unittest.TestCase):
    def test_connect_arms_and_reverifies_guard_before_and_after_vpn(self) -> None:
        events: list[str] = []
        session = FakeSession(events=events)
        vpn = FakeVpn(events=events)
        result = IPv6GuardLifecycle(session=session, vpn_backend=vpn).connect(Path("/tmp/piabazzite.conf"))
        self.assertEqual(result.profile_uuid, PROFILE)
        self.assertTrue(result.guard_status.protection_active)
        self.assertLess(events.index("session:guard-enable"), events.index("vpn:connect"))
        self.assertGreaterEqual(session.actions.count("guard-status"), 3)
        self.assertTrue(session.guard_active)

    def test_connect_failure_with_verified_vpn_down_releases_guard(self) -> None:
        session = FakeSession()
        vpn = FakeVpn()
        vpn.fail_connect = True
        with self.assertRaises(IPv6GuardConnectError) as caught:
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).connect(Path("/tmp/piabazzite.conf"))
        self.assertFalse(caught.exception.guard_retained)
        self.assertFalse(session.guard_active)
        self.assertIn("guard-disable", session.actions)

    def test_connect_failure_with_unknown_vpn_state_keeps_guard(self) -> None:
        session = FakeSession()
        vpn = FakeVpn()
        vpn.fail_connect = True
        vpn.unknown_state = True
        with self.assertRaises(IPv6GuardConnectError) as caught:
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).connect(Path("/tmp/piabazzite.conf"))
        self.assertTrue(caught.exception.guard_retained)
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)

    def test_post_connect_guard_verification_failure_keeps_guard_and_vpn_state(self) -> None:
        session = FakeSession()
        vpn = FakeVpn()
        original = session.ipv6_guard_status
        calls = 0

        def flaky_status():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("post-connect guard status unreadable")
            return original()

        session.ipv6_guard_status = flaky_status  # type: ignore[method-assign]
        with self.assertRaises(IPv6GuardConnectError) as caught:
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).connect(Path("/tmp/piabazzite.conf"))
        self.assertTrue(caught.exception.vpn_connected)
        self.assertTrue(caught.exception.guard_retained)
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)

    def test_disconnect_stops_and_verifies_vpn_before_guard_release(self) -> None:
        events: list[str] = []
        session = FakeSession(guard_active=True, events=events)
        vpn = FakeVpn(connected=True, events=events)
        result = IPv6GuardLifecycle(session=session, vpn_backend=vpn).disconnect(PROFILE)
        self.assertFalse(result.guard_status.protection_active)
        self.assertFalse(vpn.connected)
        self.assertFalse(session.guard_active)
        self.assertLess(events.index("vpn:disconnect"), events.index("session:guard-disable"))

    def test_disconnect_handles_verified_absent_guard_without_weakening_order(self) -> None:
        session = FakeSession(guard_active=False)
        vpn = FakeVpn(connected=True)
        result = IPv6GuardLifecycle(session=session, vpn_backend=vpn).disconnect(PROFILE)
        self.assertFalse(result.guard_status.present)
        self.assertFalse(vpn.connected)
        self.assertIn("disconnect", vpn.actions)
        self.assertIn("guard-disable", session.actions)

    def test_disconnect_failure_never_releases_guard(self) -> None:
        session = FakeSession(guard_active=True)
        vpn = FakeVpn(connected=True)
        vpn.fail_disconnect = True
        with self.assertRaises(IPv6GuardDisconnectError) as caught:
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).disconnect(PROFILE)
        self.assertFalse(caught.exception.vpn_disconnected)
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)

    def test_guard_release_failure_reports_vpn_down_and_retains_guard(self) -> None:
        session = FakeSession(guard_active=True)
        session.fail_disable = True
        vpn = FakeVpn(connected=True)
        with self.assertRaises(IPv6GuardDisconnectError) as caught:
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).disconnect(PROFILE)
        self.assertTrue(caught.exception.vpn_disconnected)
        self.assertTrue(caught.exception.guard_retained)
        self.assertFalse(vpn.connected)
        self.assertTrue(session.guard_active)

    def test_startup_adopts_verified_guard_when_vpn_is_still_connected(self) -> None:
        session = FakeSession(guard_active=True)
        vpn = FakeVpn(connected=True)
        result = IPv6GuardLifecycle(session=session, vpn_backend=vpn).reconcile_startup()
        self.assertTrue(result.adopted)
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)

    def test_startup_clears_stale_guard_only_when_vpn_is_down(self) -> None:
        session = FakeSession(guard_active=True)
        vpn = FakeVpn(connected=False)
        result = IPv6GuardLifecycle(session=session, vpn_backend=vpn).reconcile_startup()
        self.assertEqual(result.disposition, "cleared-stale-guard")
        self.assertFalse(session.guard_active)

    def test_startup_stops_connected_vpn_if_guard_is_absent(self) -> None:
        session = FakeSession(guard_active=False)
        vpn = FakeVpn(connected=True)
        result = IPv6GuardLifecycle(session=session, vpn_backend=vpn).reconcile_startup()
        self.assertEqual(result.disposition, "stopped-unprotected-vpn")
        self.assertFalse(vpn.connected)

    def test_startup_unknown_vpn_state_never_releases_existing_guard(self) -> None:
        session = FakeSession(guard_active=True)
        vpn = FakeVpn(connected=False)
        vpn.unknown_state = True
        with self.assertRaises(RuntimeError):
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).reconcile_startup()
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)

    def test_startup_refuses_if_unprotected_vpn_cannot_be_stopped(self) -> None:
        session = FakeSession(guard_active=False)
        vpn = FakeVpn(connected=True)
        vpn.fail_disconnect = True
        with self.assertRaises(IPv6GuardStartupError):
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).reconcile_startup()

    def test_small_guard_refuses_to_operate_with_full_kill_switch_present(self) -> None:
        session = FakeSession(full_present=True)
        vpn = FakeVpn()
        with self.assertRaises(IPv6GuardStateError):
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).connect(Path("/tmp/piabazzite.conf"))
        self.assertNotIn("guard-enable", session.actions)
        self.assertNotIn("connect", vpn.actions)

    def test_unexpected_loss_unknown_vpn_state_never_releases_guard(self) -> None:
        session = FakeSession(guard_active=True)
        vpn = FakeVpn(connected=False)
        vpn.unknown_state = True
        with self.assertRaises(RuntimeError):
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).release_after_verified_vpn_loss()
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)

    def test_unexpected_loss_release_requires_verified_vpn_down(self) -> None:
        session = FakeSession(guard_active=True)
        vpn = FakeVpn(connected=True)
        with self.assertRaises(IPv6GuardDisconnectError):
            IPv6GuardLifecycle(session=session, vpn_backend=vpn).release_after_verified_vpn_loss()
        self.assertTrue(session.guard_active)
        self.assertNotIn("guard-disable", session.actions)


if __name__ == "__main__":
    unittest.main()
