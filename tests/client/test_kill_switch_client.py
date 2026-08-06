from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pia_bazzite.kill_switch_client import (
    AuthorizationDeniedError,
    HelperCommandError,
    HelperNotInstalledError,
    HelperTimeoutError,
    InvalidHelperResponseError,
    KillSwitchClient,
    ProcessResult,
    ProtocolMismatchError,
)


class FakeRunner:
    def __init__(self, result: ProcessResult | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[list[str], float, dict[str, str]]] = []

    def run(self, arguments, *, timeout, environment):
        self.calls.append((list(arguments), timeout, dict(environment)))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def payload(
    *,
    action: str = "status",
    ok: bool = True,
    state: str = "disabled",
    present: bool = False,
    verified: bool = True,
    protocol_version: int = 1,
    helper_stage: int = 5,
    problems: list[str] | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "ok": ok,
        "schema_version": 1,
        "protocol_version": protocol_version,
        "helper_stage": helper_stage,
        "action": action,
    }
    if ok:
        document.update(
            {
                "state": state,
                "present": present,
                "verified": verified,
                "table": "pia_bazzite_killswitch",
                "table_generation": 1,
                "capabilities": [
                    "set-interfaces",
                    "set-endpoints",
                    "add-endpoint",
                    "remove-endpoint",
                ],
                "problems": [] if problems is None else problems,
            }
        )
    else:
        document.update({"error": "nftables", "message": "nft failed"})
    return document


class KillSwitchClientTests(unittest.TestCase):
    def make_client(self, result: ProcessResult | BaseException, **kwargs) -> KillSwitchClient:
        runner = FakeRunner(result)
        client = KillSwitchClient(
            runner=runner,
            helper_path=Path("/fixed/helper"),
            pkexec_path=Path("/fixed/pkexec"),
            environment={
                "DISPLAY": ":0",
                "WAYLAND_DISPLAY": "wayland-0",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "LD_PRELOAD": "/tmp/evil.so",
                "LD_LIBRARY_PATH": "/tmp/evil",
                "PYTHONPATH": "/tmp/evil",
                "SUDO_UID": "1000",
                "PATH": "/tmp/evil",
            },
            **kwargs,
        )
        client._preflight = lambda: None  # type: ignore[method-assign]
        return client

    def test_status_uses_fixed_argv_without_shell_and_preserves_session_environment(self):
        runner = FakeRunner(
            ProcessResult(0, json.dumps(payload()), "")
        )
        client = KillSwitchClient(
            runner=runner,
            helper_path=Path("/fixed/helper"),
            pkexec_path=Path("/fixed/pkexec"),
            environment={
                "DISPLAY": ":0",
                "WAYLAND_DISPLAY": "wayland-0",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "LD_PRELOAD": "/tmp/evil.so",
                "LD_LIBRARY_PATH": "/tmp/evil",
                "PYTHONPATH": "/tmp/evil",
                "SUDO_UID": "1000",
                "PATH": "/tmp/evil",
            },
        )
        client._preflight = lambda: None  # type: ignore[method-assign]

        status = client.status()

        self.assertEqual(status.state, "disabled")
        self.assertFalse(status.protection_active)
        arguments, timeout, environment = runner.calls[0]
        self.assertEqual(
            arguments,
            [
                "/fixed/pkexec",
                "--disable-internal-agent",
                "/fixed/helper",
                "status",
            ],
        )
        self.assertEqual(timeout, 120.0)
        self.assertEqual(environment["DISPLAY"], ":0")
        self.assertEqual(environment["WAYLAND_DISPLAY"], "wayland-0")
        self.assertEqual(
            environment["DBUS_SESSION_BUS_ADDRESS"],
            "unix:path=/run/user/1000/bus",
        )
        self.assertEqual(environment["PATH"], "/usr/sbin:/usr/bin:/sbin:/bin")
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertNotIn("LD_LIBRARY_PATH", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("SUDO_UID", environment)

    def test_enable_builds_only_fixed_repeated_arguments(self):
        active = payload(action="enable", state="active", present=True)
        client = self.make_client(ProcessResult(0, json.dumps(active), ""))

        status = client.enable(
            interfaces=["wlo1", "enp5s0"],
            endpoints=["1.2.3.4:1337", "[2001:db8::1]:1337"],
        )

        self.assertTrue(status.protection_active)
        runner = client.runner
        self.assertIsInstance(runner, FakeRunner)
        arguments = runner.calls[0][0]
        self.assertEqual(
            arguments,
            [
                "/fixed/pkexec",
                "--disable-internal-agent",
                "/fixed/helper",
                "enable",
                "--interface",
                "wlo1",
                "--interface",
                "enp5s0",
                "--endpoint",
                "1.2.3.4:1337",
                "--endpoint",
                "[2001:db8::1]:1337",
            ],
        )

    def test_empty_or_control_character_arguments_are_rejected_before_runner(self):
        client = self.make_client(ProcessResult(0, "{}", ""))
        with self.assertRaises(ValueError):
            client.set_interfaces([])
        with self.assertRaises(ValueError):
            client.add_endpoint("1.2.3.4:1337\n--evil")
        runner = client.runner
        self.assertIsInstance(runner, FakeRunner)
        self.assertEqual(runner.calls, [])

    def test_authorization_denial_codes_are_distinguished_from_helper_errors(self):
        for returncode in (126, 127):
            with self.subTest(returncode=returncode):
                client = self.make_client(
                    ProcessResult(returncode, "", "Not authorized")
                )
                with self.assertRaises(AuthorizationDeniedError):
                    client.status()

    def test_structured_helper_error_is_preserved(self):
        document = payload(action="enable", ok=False)
        client = self.make_client(ProcessResult(4, "", json.dumps(document)))
        with self.assertRaises(HelperCommandError) as caught:
            client.enable(interfaces=["wlo1"], endpoints=["1.2.3.4:1337"])
        self.assertEqual(caught.exception.kind, "nftables")
        self.assertEqual(caught.exception.action, "enable")
        self.assertEqual(caught.exception.returncode, 4)

    def test_timeout_is_reported_separately(self):
        client = self.make_client(
            subprocess.TimeoutExpired(cmd=["pkexec"], timeout=3)
        )
        with self.assertRaises(HelperTimeoutError):
            client.status()

    def test_missing_helper_is_reported_before_runner(self):
        runner = FakeRunner(ProcessResult(0, json.dumps(payload()), ""))
        client = KillSwitchClient(
            runner=runner,
            helper_path=Path("/definitely/missing/helper"),
            pkexec_path=Path("/fixed/pkexec"),
        )
        with patch(
            "pia_bazzite.kill_switch_client._verify_executable",
            side_effect=[None, HelperNotInstalledError("helper missing")],
        ):
            with self.assertRaises(HelperNotInstalledError):
                client.status()
        self.assertEqual(runner.calls, [])

    def test_malformed_mixed_or_non_object_output_is_rejected(self):
        cases = [
            ProcessResult(0, "not json", ""),
            ProcessResult(0, json.dumps(payload()) + "\nnoise", ""),
            ProcessResult(0, "[]", ""),
            ProcessResult(0, json.dumps(payload()), "warning"),
            ProcessResult(4, "unexpected", json.dumps(payload(ok=False))),
        ]
        for result in cases:
            with self.subTest(result=result):
                client = self.make_client(result)
                with self.assertRaises(InvalidHelperResponseError):
                    client.status()

    def test_protocol_schema_stage_and_action_mismatches_are_rejected(self):
        cases = [
            payload(protocol_version=2),
            {**payload(), "schema_version": 2},
            payload(helper_stage=3),
            payload(action="disable"),
        ]
        for document in cases:
            with self.subTest(document=document):
                client = self.make_client(
                    ProcessResult(0, json.dumps(document), "")
                )
                with self.assertRaises((ProtocolMismatchError, InvalidHelperResponseError)):
                    client.status()

    def test_exit_status_and_ok_field_must_agree(self):
        success_on_failure = ProcessResult(4, "", json.dumps(payload()))
        error_on_success = ProcessResult(0, json.dumps(payload(ok=False)), "")
        for result in (success_on_failure, error_on_success):
            with self.subTest(result=result):
                client = self.make_client(result)
                with self.assertRaises(InvalidHelperResponseError):
                    client.status()

    def test_active_state_is_never_trusted_without_presence_verification_and_no_problems(self):
        cases = [
            payload(state="active", present=False),
            payload(state="active", present=True, verified=False),
            payload(state="active", present=True, problems=["missing rule"]),
            payload(state="mystery", present=True),
        ]
        for document in cases:
            with self.subTest(document=document):
                client = self.make_client(
                    ProcessResult(0, json.dumps(document), "")
                )
                with self.assertRaises(InvalidHelperResponseError):
                    client.status()

    def test_mutating_actions_require_the_expected_verified_state(self):
        disabled_enable = payload(action="enable", state="disabled", present=False)
        active_disable = payload(action="disable", state="active", present=True)
        client = self.make_client(ProcessResult(0, json.dumps(disabled_enable), ""))
        with self.assertRaises(InvalidHelperResponseError):
            client.enable(interfaces=["wlo1"], endpoints=["1.2.3.4:1337"])
        client = self.make_client(ProcessResult(0, json.dumps(active_disable), ""))
        with self.assertRaises(InvalidHelperResponseError):
            client.disable()

    def test_timeout_range_is_bounded(self):
        with self.assertRaises(ValueError):
            KillSwitchClient(timeout=0)
        with self.assertRaises(ValueError):
            KillSwitchClient(timeout=301)


if __name__ == "__main__":
    unittest.main()
