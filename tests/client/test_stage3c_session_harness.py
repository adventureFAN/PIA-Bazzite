from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "tools/pia-bazzite-stage3c-session-netns-bridge.py"
DRIVER = ROOT / "tools/pia-bazzite-stage3c-session-driver.py"
HARNESS = ROOT / "tools/kill-switch-session-stage3c-namespace-test.sh"
SESSION_CLIENT = ROOT / "pia_bazzite/kill_switch_session.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stage3CBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = load(BRIDGE, "stage3c_bridge")

    def test_bridge_accepts_no_arguments_and_enters_only_tokenized_namespace(self):
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("pia-bazzite-stage3c-session-netns-bridge-", source)
        self.assertIn('NAMESPACE_PREFIX = "pia-h3c-client-"', source)
        self.assertIn("pia-bazzite-kill-switch-session", source)
        self.assertIn("os.execve", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)
        self.assertEqual(
            self.bridge.build_exec_argv("pia-h3c-client-123"),
            [
                "/usr/bin/ip",
                "netns",
                "exec",
                "pia-h3c-client-123",
                "/usr/local/libexec/pia-bazzite/pia-bazzite-kill-switch-session",
            ],
        )


class Stage3CDriverHarnessTests(unittest.TestCase):
    def test_driver_exposes_only_fixed_operations(self):
        source = DRIVER.read_text(encoding="utf-8")
        for operation in (
            '"status"', '"enable"', '"set-endpoints"', '"set-interfaces"',
            '"add-endpoint"', '"remove-endpoint"', '"disable"',
            '"emergency-reset"', '"close"',
        ):
            self.assertIn(operation, source)
        self.assertIn("KillSwitchSessionClient", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)

    def test_real_harness_uses_one_controller_process_and_noninteractive_cleanup(self):
        source = HARNESS.read_text(encoding="utf-8")
        self.assertIn("coproc H3C_CONTROLLER", source)
        self.assertIn("No further Polkit dialogs should appear", source)
        self.assertIn("sudo -n", source)
        self.assertIn("trap cleanup EXIT", source)
        self.assertNotIn("sudo rm -rf", source)
        self.assertEqual(source.count('python3 -I "$DRIVER" "$BRIDGE_TARGET" session'), 1)

    def test_session_transport_starts_pkexec_only_in_open(self):
        source = SESSION_CLIENT.read_text(encoding="utf-8")
        self.assertIn('"--disable-internal-agent"', source)
        self.assertEqual(source.count("self.transport.start("), 1)
        self.assertNotIn("shell=True", source)


if __name__ == "__main__":
    unittest.main()
