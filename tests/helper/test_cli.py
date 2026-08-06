from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock, patch

from helper.pia_bazzite_kill_switch_helper import cli
from helper.pia_bazzite_kill_switch_helper.core import (
    CHAIN_COMMENT,
    CHAIN_NAME,
    ENDPOINT_SET_V4,
    ENDPOINT_SET_V6,
    PHYSICAL_INTERFACE_SET,
    TABLE_COMMENT,
    TABLE_NAME,
)
from helper.pia_bazzite_kill_switch_helper.protocol import PROTOCOL_VERSION
from helper.pia_bazzite_kill_switch_helper.runner import CommandResult


def valid_table_payload() -> str:
    comments = [
        "pia-bazzite:v1:loopback",
        "pia-bazzite:v1:dhcp4",
        "pia-bazzite:v1:dhcp6",
        "pia-bazzite:v1:ipv6-link",
        "pia-bazzite:v1:endpoint4",
        "pia-bazzite:v1:endpoint6",
        "pia-bazzite:v1:vpn-tunnel",
        "pia-bazzite:v1:block-outside-vpn",
    ]
    return json.dumps({"nftables": [
        {"table": {"family": "inet", "name": TABLE_NAME, "comment": TABLE_COMMENT}},
        {"set": {"family": "inet", "table": TABLE_NAME,
                 "name": PHYSICAL_INTERFACE_SET, "type": "ifname"}},
        {"set": {"family": "inet", "table": TABLE_NAME,
                 "name": ENDPOINT_SET_V4, "type": ["ipv4_addr", "inet_service"]}},
        {"set": {"family": "inet", "table": TABLE_NAME,
                 "name": ENDPOINT_SET_V6, "type": ["ipv6_addr", "inet_service"]}},
        {"chain": {"family": "inet", "table": TABLE_NAME, "name": CHAIN_NAME,
                   "type": "filter", "hook": "output", "prio": -100,
                   "policy": "accept", "comment": CHAIN_COMMENT}},
        *[
            {"rule": {"family": "inet", "table": TABLE_NAME, "chain": CHAIN_NAME,
                      "comment": comment}}
            for comment in comments
        ],
    ]})


class CliTests(unittest.TestCase):
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=1000)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_non_root_status_is_rejected_instead_of_claiming_disabled(self, runner_cls, geteuid) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = cli.main(["status"])
        self.assertEqual(code, cli.EXIT_PRIVILEGE)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"], "privilege")
        self.assertEqual(payload["action"], "status")
        self.assertEqual(payload["protocol_version"], PROTOCOL_VERSION)

    @patch("helper.pia_bazzite_kill_switch_helper.cli._require_isolated_network_namespace")
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_root_status_absent_is_disabled(self, runner_cls, geteuid, namespace_check) -> None:
        runner = runner_cls.return_value
        runner.table_exists.return_value = False
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["status"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["state"], "disabled")
        self.assertEqual(payload["table"], TABLE_NAME)
        self.assertEqual(payload["action"], "status")
        self.assertEqual(payload["protocol_version"], PROTOCOL_VERSION)
        self.assertIn("set-interfaces", payload["capabilities"])

    def _configured_runner(self, runner_cls):
        runner = runner_cls.return_value
        runner.table_exists.return_value = True
        runner.list_table_json.return_value = CommandResult(0, valid_table_payload(), "")
        return runner

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock")
    @patch("helper.pia_bazzite_kill_switch_helper.cli._require_isolated_network_namespace")
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_enable_checks_then_applies_then_verifies(self, runner_cls, geteuid, namespace_check, lock) -> None:
        lock.return_value.__enter__ = Mock(return_value=None)
        lock.return_value.__exit__ = Mock(return_value=False)
        runner = self._configured_runner(runner_cls)
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main([
                "enable", "--interface", "wlo1",
                "--endpoint", "198.51.100.1:1337",
            ])
        self.assertEqual(code, 0)
        runner.check_script.assert_called_once()
        runner.apply_script.assert_called_once()
        self.assertEqual(runner.check_script.call_args.args[0], runner.apply_script.call_args.args[0])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["action"], "enable")
        self.assertTrue(payload["verified"])

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock")
    @patch("helper.pia_bazzite_kill_switch_helper.cli._require_isolated_network_namespace")
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_set_endpoints_is_checked_applied_and_verified(self, runner_cls, geteuid, namespace_check, lock) -> None:
        lock.return_value.__enter__ = Mock(return_value=None)
        lock.return_value.__exit__ = Mock(return_value=False)
        runner = self._configured_runner(runner_cls)
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main([
                "set-endpoints",
                "--endpoint", "198.51.100.2:1443",
                "--endpoint", "[2001:db8::2]:1443",
            ])
        self.assertEqual(code, 0)
        script = runner.apply_script.call_args.args[0]
        self.assertIn("flush set", script)
        self.assertIn("198.51.100.2 . 1443", script)
        self.assertEqual(json.loads(stdout.getvalue())["action"], "set-endpoints")

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock")
    @patch("helper.pia_bazzite_kill_switch_helper.cli._require_isolated_network_namespace")
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_set_interfaces_is_checked_applied_and_verified(self, runner_cls, geteuid, namespace_check, lock) -> None:
        lock.return_value.__enter__ = Mock(return_value=None)
        lock.return_value.__exit__ = Mock(return_value=False)
        runner = self._configured_runner(runner_cls)
        with patch("sys.stdout", io.StringIO()):
            code = cli.main(["set-interfaces", "--interface", "enp5s0"])
        self.assertEqual(code, 0)
        self.assertIn('"enp5s0"', runner.apply_script.call_args.args[0])

    @patch("helper.pia_bazzite_kill_switch_helper.cli._exclusive_lock")
    @patch("helper.pia_bazzite_kill_switch_helper.cli._require_isolated_network_namespace")
    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_validation_error_never_calls_nft(
        self, runner_cls, geteuid, namespace_check, lock
    ) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = cli.main([
                "enable", "--interface", "wlo1;id",
                "--endpoint", "198.51.100.1:1337",
            ])
        self.assertEqual(code, cli.EXIT_VALIDATION)
        lock.assert_not_called()
        runner_cls.assert_not_called()

    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_missing_required_argument_returns_json_without_nft(self, runner_cls) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = cli.main(["set-endpoints"])
        self.assertEqual(code, cli.EXIT_VALIDATION)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["action"], "set-endpoints")
        self.assertEqual(payload["error"], "validation")
        runner_cls.assert_not_called()

    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_unknown_action_returns_json_without_nft(self, runner_cls) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = cli.main(["not-a-real-action"])
        self.assertEqual(code, cli.EXIT_VALIDATION)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["action"], "unknown")
        self.assertEqual(payload["error"], "validation")
        runner_cls.assert_not_called()

    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_host_network_namespace_is_refused_before_nft(self, runner_cls, geteuid) -> None:
        stderr = io.StringIO()
        same_namespace = type("Stat", (), {"st_ino": 42})()
        with patch("helper.pia_bazzite_kill_switch_helper.cli.os.stat", return_value=same_namespace), \
                patch("sys.stderr", stderr):
            code = cli.main(["status"])
        self.assertEqual(code, cli.EXIT_SAFETY)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"], "safety-boundary")
        runner_cls.assert_not_called()

    @patch("helper.pia_bazzite_kill_switch_helper.cli.os.geteuid", return_value=0)
    @patch("helper.pia_bazzite_kill_switch_helper.cli.NftRunner")
    def test_verified_installed_boundary_may_use_host_namespace(self, runner_cls, geteuid) -> None:
        runner = runner_cls.return_value
        runner.table_exists.return_value = False
        stdout = io.StringIO()
        same_namespace = type("Stat", (), {"st_ino": 42})()
        with patch(
            "helper.pia_bazzite_kill_switch_helper.cli.os.stat",
            return_value=same_namespace,
        ), patch("sys.stdout", stdout):
            code = cli.main(["status"], trusted_host=True)
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["state"], "disabled")
        self.assertEqual(payload["table"], "pia_bazzite_killswitch")


if __name__ == "__main__":
    unittest.main()
