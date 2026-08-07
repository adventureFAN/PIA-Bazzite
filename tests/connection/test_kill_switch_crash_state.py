from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from pia_bazzite.kill_switch_client import KillSwitchStatus
from pia_bazzite.kill_switch_crash_state import (
    CrashRecoveryDisposition,
    CrashRecoveryJournal,
    CrashRecoveryPhase,
    CrashRecoveryRecord,
    CrashRecoveryStateError,
    CrashRecoveryStore,
    CrashRecoveryVerifier,
)
from pia_bazzite.kill_switch_recovery import FirewallRoutePlan


PROFILE_UUID = "11111111-2222-4333-8444-555555555555"
OTHER_PROFILE_UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SESSION_UUID = "99999999-8888-4777-8666-555555555555"


def route_plan() -> FirewallRoutePlan:
    return FirewallRoutePlan.create(
        physical_interfaces=("wlo1",),
        endpoints=("198.51.100.10:1337",),
    )


def record(*, phase: CrashRecoveryPhase = CrashRecoveryPhase.PROTECTED_CONNECTED) -> CrashRecoveryRecord:
    return CrashRecoveryRecord.create(
        phase=phase,
        profile_uuid=PROFILE_UUID,
        route_plan=route_plan(),
        session_id=SESSION_UUID,
    )


def helper_status(
    *,
    active: bool,
    verified: bool = True,
    interfaces: tuple[str, ...] = ("wlo1",),
    endpoints: tuple[str, ...] = ("198.51.100.10:1337",),
) -> KillSwitchStatus:
    return KillSwitchStatus(
        action="status",
        state="active" if active else "disabled",
        present=active,
        verified=verified,
        table="pia_bazzite_killswitch",
        table_generation=1,
        capabilities=("inspect-route",),
        problems=(),
        payload={},
        physical_interfaces=interfaces if active else (),
        endpoints=endpoints if active else (),
    )


class CrashRecoveryRecordTests(unittest.TestCase):
    def test_record_round_trip_is_canonical_and_checksum_protected(self) -> None:
        original = record()
        restored = CrashRecoveryRecord.from_document(original.to_document())
        self.assertEqual(restored, original)
        self.assertEqual(restored.route_plan, route_plan())

        changed = original.to_document()
        changed["endpoints"] = ["198.51.100.20:1337"]
        with self.assertRaises(CrashRecoveryStateError):
            CrashRecoveryRecord.from_document(changed)

    def test_record_rejects_unknown_fields_invalid_uuid_and_unsafe_route(self) -> None:
        document = record().to_document()
        document["extra"] = True
        with self.assertRaises(CrashRecoveryStateError):
            CrashRecoveryRecord.from_document(document)

        with self.assertRaises(CrashRecoveryStateError):
            CrashRecoveryRecord.create(
                phase=CrashRecoveryPhase.PROTECTED_CONNECTED,
                profile_uuid="not-a-uuid",
                route_plan=route_plan(),
            )

        with self.assertRaises(Exception):
            FirewallRoutePlan.create(
                physical_interfaces=("lo",),
                endpoints=("198.51.100.10:1337",),
            )

    def test_recovered_baseline_checks_every_fixed_path(self) -> None:
        baseline = record().conservative_probe_baseline
        self.assertTrue(baseline.ipv4_tcp)
        self.assertTrue(baseline.ipv6_tcp)
        self.assertTrue(baseline.dns_tcp)
        self.assertTrue(baseline.dns_udp)


class CrashRecoveryStoreTests(unittest.TestCase):
    def test_atomic_store_uses_private_regular_file_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash-recovery-v1.json"
            store = CrashRecoveryStore(path)
            store.save(record())

            metadata = path.lstat()
            self.assertTrue(path.is_file())
            self.assertEqual(metadata.st_mode & 0o777, 0o600)
            self.assertEqual(metadata.st_uid, os.geteuid())
            self.assertEqual(store.load(), record())

            store.clear()
            self.assertFalse(path.exists())
            self.assertIsNone(store.load())

    def test_store_rejects_symlink_broad_permissions_and_partial_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("do not replace", encoding="utf-8")
            link = root / "crash-recovery-v1.json"
            link.symlink_to(target)
            with self.assertRaises(CrashRecoveryStateError):
                CrashRecoveryStore(link).save(record())
            self.assertEqual(target.read_text(encoding="utf-8"), "do not replace")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash-recovery-v1.json"
            path.write_text(json.dumps(record().to_document()), encoding="ascii")
            path.chmod(0o644)
            with self.assertRaises(CrashRecoveryStateError):
                CrashRecoveryStore(path).load()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash-recovery-v1.json"
            path.write_text('{"kind":', encoding="ascii")
            path.chmod(0o600)
            with self.assertRaises(CrashRecoveryStateError):
                CrashRecoveryStore(path).load()

    def test_store_requires_absolute_path_and_safe_parent(self) -> None:
        with self.assertRaises(CrashRecoveryStateError):
            CrashRecoveryStore(Path("relative.json"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o777)
            with self.assertRaises(CrashRecoveryStateError):
                CrashRecoveryStore(root / "record.json").save(record())

    def test_verified_release_cleanup_unlinks_corrupt_regular_file_and_symlink_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "crash-recovery-v1.json"
            path.write_text("not-json", encoding="ascii")
            path.chmod(0o644)
            store = CrashRecoveryStore(path)
            store.discard_untrusted_after_verified_release()
            self.assertFalse(path.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "do-not-touch"
            target.write_text("preserved", encoding="utf-8")
            path = root / "crash-recovery-v1.json"
            path.symlink_to(target)
            store = CrashRecoveryStore(path)
            store.discard_untrusted_after_verified_release()
            self.assertFalse(path.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "preserved")

    def test_verified_release_cleanup_refuses_directories_special_files_and_unsafe_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "crash-recovery-v1.json"
            path.mkdir()
            with self.assertRaises(CrashRecoveryStateError):
                CrashRecoveryStore(path).discard_untrusted_after_verified_release()
            self.assertTrue(path.is_dir())

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "crash-recovery-v1.json"
                os.mkfifo(path, 0o600)
                with self.assertRaises(CrashRecoveryStateError):
                    CrashRecoveryStore(path).discard_untrusted_after_verified_release()
                self.assertTrue(path.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o777)
            path = root / "crash-recovery-v1.json"
            path.write_text("not-json", encoding="ascii")
            with self.assertRaises(CrashRecoveryStateError):
                CrashRecoveryStore(path).discard_untrusted_after_verified_release()
            self.assertTrue(path.exists())


class CrashRecoveryJournalTests(unittest.TestCase):
    def test_journal_keeps_one_session_id_across_connected_and_blocking_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash-recovery-v1.json"
            journal = CrashRecoveryJournal(
                CrashRecoveryStore(path),
                session_id=SESSION_UUID,
            )

            connected = journal.save_connected(
                profile_uuid=PROFILE_UUID,
                route_plan=route_plan(),
            )
            blocking = journal.save_blocking(
                profile_uuid=PROFILE_UUID,
                route_plan=route_plan(),
            )

            self.assertEqual(connected.session_id, SESSION_UUID)
            self.assertEqual(blocking.session_id, SESSION_UUID)
            self.assertEqual(blocking.phase, CrashRecoveryPhase.PROTECTED_BLOCKING)
            self.assertEqual(CrashRecoveryStore(path).load(), blocking)

            journal.clear()
            self.assertFalse(path.exists())

    def test_journal_accepts_only_validated_store_and_route_values(self) -> None:
        with self.assertRaises(CrashRecoveryStateError):
            CrashRecoveryJournal(object())  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as directory:
            journal = CrashRecoveryJournal(
                CrashRecoveryStore(Path(directory) / "record.json"),
                session_id=SESSION_UUID,
            )
            with self.assertRaises(CrashRecoveryStateError):
                journal.save_connected(
                    profile_uuid="not-a-uuid",
                    route_plan=route_plan(),
                )


class CrashRecoveryVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = CrashRecoveryVerifier()

    def test_exact_live_connected_state_is_adopted(self) -> None:
        decision = self.verifier.evaluate(
            record=record(),
            helper_status=helper_status(active=True),
            vpn_connected=True,
            active_profile_uuid=PROFILE_UUID,
        )
        self.assertEqual(decision.disposition, CrashRecoveryDisposition.ADOPT_CONNECTED)
        self.assertTrue(decision.adopted)
        self.assertEqual(decision.route_plan, route_plan())
        self.assertTrue(decision.probe_baseline.dns_udp)  # type: ignore[union-attr]

    def test_exact_live_blocking_state_is_adopted_conservatively(self) -> None:
        decision = self.verifier.evaluate(
            record=record(phase=CrashRecoveryPhase.PROTECTED_CONNECTED),
            helper_status=helper_status(active=True),
            vpn_connected=False,
        )
        self.assertEqual(decision.disposition, CrashRecoveryDisposition.ADOPT_BLOCKING)
        self.assertTrue(decision.adopted)
        baseline = decision.probe_baseline
        self.assertIsNotNone(baseline)
        self.assertTrue(all((baseline.ipv4_tcp, baseline.ipv6_tcp, baseline.dns_tcp, baseline.dns_udp)))

    def test_absent_table_clears_only_stale_record(self) -> None:
        stale = self.verifier.evaluate(
            record=record(),
            helper_status=helper_status(active=False),
            vpn_connected=False,
        )
        empty = self.verifier.evaluate(
            record=None,
            helper_status=helper_status(active=False),
            vpn_connected=False,
        )
        self.assertEqual(stale.disposition, CrashRecoveryDisposition.CLEAR_STALE_RECORD)
        self.assertEqual(empty.disposition, CrashRecoveryDisposition.NO_RECOVERY)

    def test_active_table_without_record_is_never_adopted(self) -> None:
        decision = self.verifier.evaluate(
            record=None,
            helper_status=helper_status(active=True),
            vpn_connected=False,
        )
        self.assertEqual(decision.disposition, CrashRecoveryDisposition.REFUSE_UNOWNED_LOCK)
        self.assertFalse(decision.adopted)

    def test_route_profile_and_host_mismatches_fail_closed(self) -> None:
        route_mismatch = self.verifier.evaluate(
            record=record(),
            helper_status=helper_status(
                active=True,
                endpoints=("198.51.100.20:1337",),
            ),
            vpn_connected=True,
            active_profile_uuid=PROFILE_UUID,
        )
        profile_mismatch = self.verifier.evaluate(
            record=record(),
            helper_status=helper_status(active=True),
            vpn_connected=True,
            active_profile_uuid=OTHER_PROFILE_UUID,
        )
        inconsistent = self.verifier.evaluate(
            record=record(),
            helper_status=helper_status(active=False),
            vpn_connected=True,
            active_profile_uuid=PROFILE_UUID,
        )
        self.assertEqual(route_mismatch.disposition, CrashRecoveryDisposition.REFUSE_ROUTE_MISMATCH)
        self.assertEqual(profile_mismatch.disposition, CrashRecoveryDisposition.REFUSE_PROFILE_MISMATCH)
        self.assertEqual(inconsistent.disposition, CrashRecoveryDisposition.REFUSE_INCONSISTENT_HOST)
        self.assertFalse(route_mismatch.adopted)
        self.assertFalse(profile_mismatch.adopted)
        self.assertFalse(inconsistent.adopted)

    def test_unverified_helper_status_is_never_adopted(self) -> None:
        decision = self.verifier.evaluate(
            record=record(),
            helper_status=helper_status(active=True, verified=False),
            vpn_connected=False,
        )
        self.assertEqual(decision.disposition, CrashRecoveryDisposition.REFUSE_UNVERIFIED_LOCK)
        self.assertFalse(decision.adopted)


if __name__ == "__main__":
    unittest.main()
