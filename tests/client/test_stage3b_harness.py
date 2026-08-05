from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "tools/pia-bazzite-stage3-client-netns-bridge.py"
DRIVER = ROOT / "tools/pia-bazzite-stage3-client-driver.py"
PROBE = ROOT / "tools/pia-bazzite-stage3-client-probe.py"
SHIM = ROOT / "tools/pia-bazzite-stage3-client-process-shim.py"
HARNESS = ROOT / "tools/kill-switch-client-stage3b-namespace-test.sh"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stage3BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = load(BRIDGE, "stage3_bridge")

    def test_bridge_accepts_only_exact_fixed_client_requests(self):
        accepted = {
            "status": ["status"],
            "enable": [
                "enable", "--interface", "wan0",
                "--endpoint", "198.51.100.10:1337",
                "--endpoint", "[2001:db8:100::10]:1337",
            ],
            "set-endpoints": [
                "set-endpoints",
                "--endpoint", "198.51.100.11:1443",
                "--endpoint", "[2001:db8:100::11]:1443",
            ],
            "set-interfaces": ["set-interfaces", "--interface", "lan0"],
            "disable": ["disable"],
        }
        for action, argv in accepted.items():
            with self.subTest(action=action):
                parsed_action, arguments = self.bridge.parse_request(argv)
                self.assertEqual(parsed_action, action)
                self.assertEqual(tuple(argv[1:]), arguments)
        rejected = [
            [],
            ["status", "extra"],
            ["enable", "--interface", "wlo1"],
            ["disable", ";", "id"],
            ["unknown"],
        ]
        for argv in rejected:
            with self.subTest(argv=argv):
                with self.assertRaises(self.bridge.BridgeError):
                    self.bridge.parse_request(argv)

    def test_bridge_uses_fixed_paths_no_shell_and_tokenized_namespace(self):
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("pia-bazzite-stage3-client-netns-bridge-", source)
        self.assertIn('NAMESPACE_PREFIX = "pia-h3-client-"', source)
        self.assertIn("os.execve", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("subprocess", source)


class Stage3DriverAndProbeTests(unittest.TestCase):
    def test_driver_exposes_only_fixed_client_operations(self):
        source = DRIVER.read_text(encoding="utf-8")
        for operation in (
            '"status"', '"enable"', '"set-endpoints"', '"set-interfaces"',
            '"add-endpoint"', '"remove-endpoint"', '"disable"',
            '"emergency-reset"',
        ):
            self.assertIn(operation, source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("subprocess", source)

    def test_probe_is_network_free_and_fixed_path_only(self):
        source = PROBE.read_text(encoding="utf-8")
        self.assertNotIn("socket", source)
        self.assertNotIn("nft", source)
        self.assertNotIn("NetworkManager", source)
        self.assertNotIn("subprocess", source)
        self.assertIn("INVALID_PATH", source)
        self.assertIn("TIMEOUT_PATH", source)

    def test_process_shim_accepts_only_fixed_probe_argv(self):
        source = SHIM.read_text(encoding="utf-8")
        self.assertIn("--disable-internal-agent", source)
        self.assertIn("ALLOWED_HELPERS", source)
        self.assertIn("os.execve", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)

    def test_real_harness_disables_terminal_agent_and_noninteractive_cleanup(self):
        source = HARNESS.read_text(encoding="utf-8")
        client_source = (ROOT / "pia_bazzite/kill_switch_client.py").read_text(encoding="utf-8")
        self.assertIn("--disable-internal-agent", client_source)
        self.assertIn("pkcheck --revoke-temp", source)
        self.assertIn("sudo -n", source)
        self.assertIn("trap cleanup EXIT", source)
        self.assertNotIn("sudo rm -rf", source)


if __name__ == "__main__":
    unittest.main()
