from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from pia_bazzite.emergency_reset import EmergencyResetError, run_verified_emergency_reset
from pia_bazzite.kill_switch_client import KillSwitchStatus
from pia_bazzite.kill_switch_crash_state import CrashRecoveryStore
from pia_bazzite.network_manager import ConnectionState


def disabled_status() -> KillSwitchStatus:
    return KillSwitchStatus(
        action="emergency-reset",
        state="disabled",
        present=False,
        verified=True,
        table="pia_bazzite_killswitch",
        table_generation=1,
        capabilities=("inspect-route",),
        problems=(),
        payload={},
    )


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def emergency_reset(self) -> KillSwitchStatus:
        self.calls.append("emergency-reset")
        return disabled_status()


class FakeVpn:
    def __init__(self, *, connected: bool, refuses_disconnect: bool = False) -> None:
        self.connected = connected
        self.refuses_disconnect = refuses_disconnect
        self.calls: list[str] = []

    def connection_state(self) -> ConnectionState:
        self.calls.append("state")
        return ConnectionState(self.connected, "11111111-1111-1111-1111-111111111111" if self.connected else "")

    def disconnect(self, profile_uuid: str = "") -> None:
        self.calls.append(f"disconnect:{profile_uuid}")
        if not self.refuses_disconnect:
            self.connected = False


class RecordingStore(CrashRecoveryStore):
    def __init__(self, path: Path, events: list[str]) -> None:
        super().__init__(path)
        self.events = events

    def discard_untrusted_after_verified_release(self) -> None:
        self.events.append("record-cleanup")
        super().discard_untrusted_after_verified_release()


class OrderedClient(FakeClient):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def emergency_reset(self) -> KillSwitchStatus:
        self.events.append("firewall-reset")
        return super().emergency_reset()


class OrderedVpn(FakeVpn):
    def __init__(self, events: list[str]) -> None:
        super().__init__(connected=True)
        self.events = events

    def connection_state(self) -> ConnectionState:
        state = super().connection_state()
        self.events.append("vpn-up" if state.connected else "vpn-down")
        return state

    def disconnect(self, profile_uuid: str = "") -> None:
        self.events.append("vpn-disconnect")
        super().disconnect(profile_uuid)


class EmergencyResetTests(unittest.TestCase):
    def test_reset_is_vpn_first_then_firewall_then_record_cleanup(self) -> None:
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "state"
            parent.mkdir(mode=0o700)
            store = RecordingStore(parent / "recovery.json", events)
            vpn = OrderedVpn(events)
            client = OrderedClient(events)

            result = run_verified_emergency_reset(
                client=client,
                vpn_backend=vpn,
                recovery_store=store,
            )

        self.assertTrue(result.vpn_was_connected)
        self.assertFalse(result.firewall_status.present)
        self.assertLess(events.index("vpn-disconnect"), events.index("vpn-down"))
        self.assertLess(events.index("vpn-down"), events.index("firewall-reset"))
        self.assertLess(events.index("firewall-reset"), events.index("record-cleanup"))

    def test_reset_never_touches_firewall_if_vpn_cannot_be_verified_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "state"
            parent.mkdir(mode=0o700)
            client = FakeClient()
            vpn = FakeVpn(connected=True, refuses_disconnect=True)
            store = CrashRecoveryStore(parent / "recovery.json")

            with self.assertRaises(EmergencyResetError):
                run_verified_emergency_reset(
                    client=client,
                    vpn_backend=vpn,
                    recovery_store=store,
                )

        self.assertEqual(client.calls, [])

    def test_already_disconnected_host_can_release_fixed_firewall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "state"
            parent.mkdir(mode=0o700)
            client = FakeClient()
            vpn = FakeVpn(connected=False)
            store = CrashRecoveryStore(parent / "recovery.json")

            result = run_verified_emergency_reset(
                client=client,
                vpn_backend=vpn,
                recovery_store=store,
            )

        self.assertFalse(result.vpn_was_connected)
        self.assertEqual(client.calls, ["emergency-reset"])
        self.assertEqual(vpn.calls, ["state", "state"])


if __name__ == "__main__":
    unittest.main()
