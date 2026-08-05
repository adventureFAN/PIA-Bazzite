from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_SOURCE = PROJECT_ROOT / "tools" / "pia-bazzite-stage2-netns-polkit-bridge.py"
NAMESPACE_TEST = PROJECT_ROOT / "tools" / "kill-switch-polkit-stage2-helper-namespace-test.sh"
D2_NAMESPACE_TEST = PROJECT_ROOT / "tools" / "kill-switch-helper-stage2d2-namespace-test.sh"

spec = importlib.util.spec_from_file_location("stage2_netns_bridge", BRIDGE_SOURCE)
assert spec is not None and spec.loader is not None
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Stage2NamespaceBridgeTests(unittest.TestCase):
    def test_accepts_only_fixed_namespace_and_operation_shapes(self) -> None:
        self.assertEqual(
            bridge.parse_request(["pia-h2-client-12345"]),
            ("pia-h2-client-12345", "enable"),
        )
        self.assertEqual(
            bridge.parse_request(["pia-h2-client-12345", "set-endpoints"]),
            ("pia-h2-client-12345", "set-endpoints"),
        )
        for arguments in (
            [], ["pia-h2-client-1", "enable", "extra"], ["pia-h2-inet-123"],
            ["pia-h2-client-123;id"], ["pia-h2-client-"], ["default"],
            ["pia-h2-client-123", "shell"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(bridge.BridgeError):
                bridge.parse_request(arguments)

    def test_exec_argv_is_fixed_for_each_operation(self) -> None:
        self.assertEqual(bridge.build_exec_argv("pia-h2-client-99", "enable"), [
            "/usr/bin/ip", "netns", "exec", "pia-h2-client-99",
            "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper",
            "enable", "--interface", "wan0",
            "--endpoint", "198.51.100.10:1337",
            "--endpoint", "[2001:db8:100::10]:1337",
        ])
        self.assertEqual(bridge.build_exec_argv("pia-h2-client-99", "set-interfaces")[-3:], [
            "set-interfaces", "--interface", "lan0",
        ])
        self.assertEqual(bridge.build_exec_argv("pia-h2-client-99", "disable")[-1], "disable")

    def test_environment_is_reduced_and_preserves_only_pkexec_uid(self) -> None:
        self.assertEqual(bridge.sanitized_environment(1000), {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "PKEXEC_UID": "1000",
        })

    def test_bridge_uses_fixed_paths_and_no_shell(self) -> None:
        text = BRIDGE_SOURCE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/python3 -I\n"))
        self.assertIn("FIXED_OPERATIONS", text)
        self.assertIn("pia-bazzite-stage2-netns-test-bridge", text)
        self.assertIn("pia-bazzite-kill-switch-helper", text)
        self.assertIn("os.execve", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("subprocess", text)
        self.assertNotIn("eval(", text)

    def test_namespace_tests_disable_terminal_authentication_fallback(self) -> None:
        for path in (NAMESPACE_TEST, D2_NAMESPACE_TEST):
            text = path.read_text(encoding="utf-8")
            self.assertIn("--disable-internal-agent", text)
            self.assertNotIn("runuser", text)
            self.assertIn("pia-bazzite-stage2-netns-test-bridge", text)


if __name__ == "__main__":
    unittest.main()
