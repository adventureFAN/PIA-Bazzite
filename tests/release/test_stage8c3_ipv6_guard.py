from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helper.pia_bazzite_kill_switch_helper import cli
from helper.pia_bazzite_kill_switch_helper.core import (
    IPV6_GUARD_CHAIN_COMMENT,
    IPV6_GUARD_CHAIN_NAME,
    IPV6_GUARD_RULE_COMMENTS,
    IPV6_GUARD_TABLE_COMMENT,
    IPV6_GUARD_TABLE_NAME,
    TABLE_NAME,
    ipv6_guard_disabled_status,
    parse_ipv6_guard_status_json,
    render_ipv6_guard_disable_ruleset,
    render_ipv6_guard_enable_ruleset,
)
from helper.pia_bazzite_kill_switch_helper.session_entry import _parse_request
from pia_bazzite.kill_switch_client import HelperResponse, IPv6GuardStatus
from pia_bazzite.kill_switch_session import KillSwitchSessionClient


def guard_json(*, priority: int = -110, extra_rule: bool = False) -> str:
    rules = [
        {
            "rule": {
                "family": "inet",
                "table": IPV6_GUARD_TABLE_NAME,
                "chain": IPV6_GUARD_CHAIN_NAME,
                "comment": comment,
                "expr": [],
            }
        }
        for comment in sorted(IPV6_GUARD_RULE_COMMENTS)
    ]
    if extra_rule:
        rules.append(
            {
                "rule": {
                    "family": "inet",
                    "table": IPV6_GUARD_TABLE_NAME,
                    "chain": IPV6_GUARD_CHAIN_NAME,
                    "comment": "unexpected",
                    "expr": [],
                }
            }
        )
    return json.dumps(
        {
            "nftables": [
                {
                    "table": {
                        "family": "inet",
                        "name": IPV6_GUARD_TABLE_NAME,
                        "comment": IPV6_GUARD_TABLE_COMMENT,
                    }
                },
                {
                    "chain": {
                        "family": "inet",
                        "table": IPV6_GUARD_TABLE_NAME,
                        "name": IPV6_GUARD_CHAIN_NAME,
                        "type": "filter",
                        "hook": "output",
                        "prio": priority,
                        "policy": "accept",
                        "comment": IPV6_GUARD_CHAIN_COMMENT,
                    }
                },
                *rules,
            ]
        }
    )


def guard_payload(action: str, *, active: bool) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": 1,
        "protocol_version": 1,
        "helper_stage": 5,
        "action": action,
        "state": "active" if active else "disabled",
        "present": active,
        "verified": True,
        "table": IPV6_GUARD_TABLE_NAME,
        "table_generation": 1,
        "capabilities": ["ipv6-only-guard"],
        "problems": [],
    }


class IPv6GuardCoreTests(unittest.TestCase):
    def test_ruleset_is_separate_ipv6_only_and_matches_real_host_probe(self) -> None:
        ruleset = render_ipv6_guard_enable_ruleset()
        self.assertTrue(ruleset.startswith(f"destroy table inet {IPV6_GUARD_TABLE_NAME}\n"))
        self.assertIn(f"table inet {IPV6_GUARD_TABLE_NAME}", ruleset)
        self.assertNotIn(f"table inet {TABLE_NAME} {{", ruleset)
        self.assertIn("hook output priority -110; policy accept", ruleset)
        self.assertIn('oifname "lo" counter accept', ruleset)
        self.assertIn("meta nfproto ipv6", ruleset)
        self.assertIn("reject with icmpx type admin-prohibited", ruleset)
        self.assertNotIn("meta nfproto ipv4", ruleset)
        self.assertNotIn("flush ruleset", ruleset)
        self.assertEqual(
            render_ipv6_guard_disable_ruleset(),
            f"destroy table inet {IPV6_GUARD_TABLE_NAME}\n",
        )

    def test_structural_status_requires_exact_guard_shape(self) -> None:
        status = parse_ipv6_guard_status_json(guard_json())
        self.assertTrue(status["verified"])
        self.assertEqual(status["state"], "active")
        self.assertEqual(status["problems"], [])

        wrong_priority = parse_ipv6_guard_status_json(guard_json(priority=-100))
        self.assertFalse(wrong_priority["verified"])
        self.assertIn("wrong priority", " ".join(wrong_priority["problems"]))

        extra = parse_ipv6_guard_status_json(guard_json(extra_rule=True))
        self.assertFalse(extra["verified"])
        self.assertIn("unexpected", " ".join(extra["problems"]))

    def test_disabled_guard_status_cannot_be_confused_with_kill_switch(self) -> None:
        status = ipv6_guard_disabled_status()
        self.assertEqual(status["table"], IPV6_GUARD_TABLE_NAME)
        self.assertEqual(status["state"], "disabled")
        self.assertFalse(status["present"])
        self.assertEqual(status["capabilities"], ["ipv6-only-guard"])


class IPv6GuardCliTests(unittest.TestCase):
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_guard_status_checks_only_fixed_guard_table(self, runner_cls, geteuid) -> None:
        runner = runner_cls.return_value
        runner.table_exists.return_value = False
        with patch("sys.stdout") as stdout:
            stdout.write = lambda *_args, **_kwargs: None
            stdout.flush = lambda: None
            code = cli.main(["ipv6-guard-status"], trusted_host=True)
        self.assertEqual(code, 0)
        runner.table_exists.assert_called_once_with(IPV6_GUARD_TABLE_NAME)
        runner.list_table_json.assert_not_called()

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock", return_value=nullcontext())
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_guard_enable_checks_applies_and_reverifies_exact_table(
        self, runner_cls, geteuid, lock
    ) -> None:
        runner = runner_cls.return_value
        # First lookup proves the full Session Kill Switch is absent; the
        # second lookup verifies the newly installed IPv6-only guard table.
        runner.table_exists.side_effect = [False, True]
        runner.list_table_json.return_value = type(
            "Result", (), {"returncode": 0, "stdout": guard_json(), "stderr": ""}
        )()
        with patch("sys.stdout"):
            code = cli.main(["ipv6-guard-enable"], trusted_host=True)
        self.assertEqual(code, 0)
        script = runner.check_script.call_args.args[0]
        self.assertEqual(script, render_ipv6_guard_enable_ruleset())
        runner.apply_script.assert_called_once_with(script)
        runner.table_exists.assert_called_with(IPV6_GUARD_TABLE_NAME)
        runner.list_table_json.assert_called_with(IPV6_GUARD_TABLE_NAME)

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock", return_value=nullcontext())
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_guard_enable_refuses_existing_full_kill_switch(
        self, runner_cls, geteuid, lock
    ) -> None:
        runner = runner_cls.return_value
        runner.table_exists.return_value = True
        with patch("sys.stderr"):
            code = cli.main(["ipv6-guard-enable"], trusted_host=True)
        self.assertEqual(code, cli.EXIT_SAFETY)
        runner.check_script.assert_not_called()
        runner.apply_script.assert_not_called()

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock", return_value=nullcontext())
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_full_kill_switch_enable_refuses_existing_ipv6_guard(
        self, runner_cls, geteuid, lock
    ) -> None:
        runner = runner_cls.return_value
        runner.table_exists.return_value = True
        with patch("sys.stderr"):
            code = cli.main(
                [
                    "enable",
                    "--interface",
                    "wlo1",
                    "--endpoint",
                    "198.51.100.10:1337",
                ],
                trusted_host=True,
            )
        self.assertEqual(code, cli.EXIT_SAFETY)
        runner.check_script.assert_not_called()
        runner.apply_script.assert_not_called()


class IPv6GuardClientContractTests(unittest.TestCase):
    def test_client_status_requires_fixed_guard_identity(self) -> None:
        status = IPv6GuardStatus.from_response(
            HelperResponse(
                action="ipv6-guard-enable",
                returncode=0,
                payload=guard_payload("ipv6-guard-enable", active=True),
            )
        )
        self.assertTrue(status.protection_active)
        bad = guard_payload("ipv6-guard-enable", active=True)
        bad["table"] = TABLE_NAME
        with self.assertRaises(Exception):
            IPv6GuardStatus.from_response(
                HelperResponse(action="ipv6-guard-enable", returncode=0, payload=bad)
            )

    def test_session_request_schema_adds_only_fieldless_guard_actions(self) -> None:
        for action in (
            "ipv6-guard-status",
            "ipv6-guard-enable",
            "ipv6-guard-disable",
        ):
            request_id, parsed_action, argv = _parse_request(
                {"request_id": 1, "action": action}, 0
            )
            self.assertEqual(request_id, 1)
            self.assertEqual(parsed_action, action)
            self.assertEqual(argv, [action])
            with self.assertRaises(Exception):
                _parse_request(
                    {"request_id": 1, "action": action, "endpoint": "198.51.100.1:1"},
                    0,
                )

    def test_session_client_exposes_guard_actions_over_one_authenticated_session(self) -> None:
        class Transport:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []
                self.alive = False

            def start(self, arguments, *, timeout, environment):
                self.alive = True
                return {
                    "event": "ready",
                    "session_protocol_version": 1,
                    "session_schema_version": 1,
                    "protocol_version": 1,
                    "helper_stage": 5,
                    "session_pid": 4242,
                    "max_requests": 128,
                    "idle_timeout_seconds": 300,
                }

            def exchange(self, request, *, timeout):
                doc = dict(request)
                self.requests.append(doc)
                action = str(doc["action"])
                if action == "close":
                    payload = {"ok": True, "action": "close"}
                else:
                    payload = guard_payload(
                        action,
                        active=action == "ipv6-guard-enable",
                    )
                return {
                    "session_protocol_version": 1,
                    "session_schema_version": 1,
                    "session_pid": 4242,
                    "request_id": doc["request_id"],
                    "returncode": 0,
                    "payload": payload,
                }

            def is_alive(self):
                return self.alive

            def close(self, *, timeout):
                self.alive = False

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pkexec = root / "pkexec"
            session = root / "session"
            pkexec.write_text("x", encoding="utf-8")
            session.write_text("x", encoding="utf-8")
            pkexec.chmod(0o755)
            session.chmod(0o755)
            transport = Transport()
            client = KillSwitchSessionClient(
                pkexec_path=pkexec,
                session_path=session,
                transport=transport,
            )
            meta = type(
                "Meta",
                (),
                {"st_mode": 0o100755, "st_uid": 0, "st_gid": 0, "st_nlink": 1},
            )()
            with patch("pia_bazzite.kill_switch_client.Path.is_symlink", return_value=False), patch(
                "pia_bazzite.kill_switch_client.Path.lstat", return_value=meta
            ):
                client.open()
                self.assertFalse(client.ipv6_guard_status().protection_active)
                self.assertTrue(client.ipv6_guard_enable().protection_active)
                self.assertFalse(client.ipv6_guard_disable().protection_active)
                client.close()
        self.assertEqual(
            [item["action"] for item in transport.requests],
            [
                "ipv6-guard-status",
                "ipv6-guard-enable",
                "ipv6-guard-disable",
                "close",
            ],
        )


class IPv6GuardReleaseBoundaryTests(unittest.TestCase):
    def test_packaged_launchers_and_protocol_know_guard_actions(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "helper/pia-bazzite-kill-switch-helper-installed",
            "helper/pia_bazzite_kill_switch_helper/protocol.py",
            "helper/pia_bazzite_kill_switch_helper/session_entry.py",
        ):
            source = (root / relative).read_text(encoding="utf-8")
            for action in (
                "ipv6-guard-status",
                "ipv6-guard-enable",
                "ipv6-guard-disable",
            ):
                self.assertIn(action, source, relative)


if __name__ == "__main__":
    unittest.main()
