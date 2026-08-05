from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_SOURCE = PROJECT_ROOT / "tools" / "pia-bazzite-stage2-netns-polkit-bridge.py"
NAMESPACE_TEST = PROJECT_ROOT / "tools" / "kill-switch-polkit-stage2-helper-namespace-test.sh"

spec = importlib.util.spec_from_file_location("stage2_netns_bridge", BRIDGE_SOURCE)
assert spec is not None and spec.loader is not None
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Stage2NamespaceBridgeTests(unittest.TestCase):
    def test_accepts_only_fixed_client_namespace_shape(self) -> None:
        self.assertEqual(bridge.parse_namespace(["pia-h2-client-12345"]), "pia-h2-client-12345")
        for arguments in (
            [], ["pia-h2-client-1", "extra"], ["pia-h2-inet-123"],
            ["pia-h2-client-123;id"], ["pia-h2-client-"], ["default"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(bridge.BridgeError):
                bridge.parse_namespace(arguments)

    def test_exec_argv_is_entirely_fixed_except_namespace(self) -> None:
        self.assertEqual(bridge.build_exec_argv("pia-h2-client-99"), [
            "/usr/bin/ip", "netns", "exec", "pia-h2-client-99",
            "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-helper",
            "enable", "--interface", "wan0",
            "--endpoint", "198.51.100.1:1337",
            "--endpoint", "[2001:db8:10::1]:1337",
        ])

    def test_environment_is_reduced_and_preserves_only_pkexec_uid(self) -> None:
        self.assertEqual(bridge.sanitized_environment(1000), {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "PKEXEC_UID": "1000",
        })

    def test_bridge_uses_fixed_paths_and_no_shell(self) -> None:
        text = BRIDGE_SOURCE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/python3 -I\n"))
        self.assertIn("pia-bazzite-stage2-netns-test-bridge", text)
        self.assertIn("pia-bazzite-kill-switch-helper", text)
        self.assertIn("os.execve", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("subprocess", text)
        self.assertNotIn("eval(", text)

    def test_namespace_test_disables_terminal_authentication_fallback(self) -> None:
        text = NAMESPACE_TEST.read_text(encoding="utf-8")
        self.assertIn("--disable-internal-agent", text)
        self.assertNotIn("runuser", text)
        self.assertIn("pia-bazzite-stage2-netns-test-bridge", text)


if __name__ == "__main__":
    unittest.main()
