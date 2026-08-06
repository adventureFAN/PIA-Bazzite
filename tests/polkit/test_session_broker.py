from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from helper.pia_bazzite_kill_switch_helper import session_entry

ROOT = Path(__file__).resolve().parents[2]
SESSION_LAUNCHER = ROOT / "helper/pia-bazzite-kill-switch-session-installed"
INSTALLER = ROOT / "tools/pia-bazzite-stage2-helper-installer.sh"


class SessionBrokerProtocolTests(unittest.TestCase):
    def test_request_schema_is_fixed_and_monotonic(self):
        request_id, action, argv = session_entry._parse_request(
            {
                "request_id": 1,
                "action": "enable",
                "interfaces": ["wan0"],
                "endpoints": ["198.51.100.10:1337"],
            },
            0,
        )
        self.assertEqual(request_id, 1)
        self.assertEqual(action, "enable")
        self.assertEqual(
            argv,
            [
                "enable", "--interface", "wan0",
                "--endpoint", "198.51.100.10:1337",
            ],
        )
        rejected = [
            ({"request_id": 1, "action": "status", "extra": True}, 0),
            ({"request_id": 1, "action": "unknown"}, 0),
            ({"request_id": 1, "action": "status"}, 1),
            ({"request_id": "1", "action": "status"}, 0),
            ({"request_id": 1, "action": "enable", "interfaces": [], "endpoints": ["x"]}, 0),
        ]
        for document, previous in rejected:
            with self.subTest(document=document), self.assertRaises(session_entry.SessionProtocolError):
                session_entry._parse_request(document, previous)

    def test_helper_invocation_returns_one_structured_payload(self):
        payload = {
            "ok": True,
            "schema_version": 1,
            "protocol_version": 1,
            "helper_stage": 5,
            "action": "status",
        }
        with patch.object(session_entry, "helper_main", side_effect=lambda argv: print(json.dumps(payload)) or 0):
            code, returned = session_entry._invoke_helper(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(returned, payload)

    def test_session_broker_has_fixed_limits_and_no_subprocess(self):
        source = (ROOT / "helper/pia_bazzite_kill_switch_helper/session_entry.py").read_text(encoding="utf-8")
        self.assertIn("MAX_REQUESTS = 128", source)
        self.assertIn("IDLE_TIMEOUT_SECONDS = 12 * 60 * 60.0", source)
        self.assertIn("selectors", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("eval(", source)


class SessionInstallationStaticTests(unittest.TestCase):
    def test_session_launcher_verifies_before_package_import(self):
        source = SESSION_LAUNCHER.read_text(encoding="utf-8")
        verify = source.index("_verify_installation()")
        package_import = source.index("from pia_bazzite_kill_switch_helper.session_entry")
        self.assertLess(verify, package_import)
        self.assertTrue(source.startswith("#!/usr/bin/python3 -I\n"))
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)
        self.assertIn("session_main(trusted_host=True)", source)

    def test_installer_manages_session_launcher_and_module_explicitly(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("TARGET_SESSION_LAUNCHER", source)
        self.assertIn("pia-bazzite-kill-switch-session-installed", source)
        self.assertIn("session_entry.py", source)
        self.assertNotIn("rm -rf", source)


if __name__ == "__main__":
    unittest.main()
