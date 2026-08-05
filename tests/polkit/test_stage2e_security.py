from __future__ import annotations

from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECURITY_TEST = PROJECT_ROOT / "tools" / "kill-switch-helper-stage2e-security-test.sh"
SELF_TEST = PROJECT_ROOT / "tools" / "kill-switch-helper-stage2e-self-test.sh"


class Stage2ESecurityHarnessTests(unittest.TestCase):
    def test_security_test_has_noninteractive_privileged_cleanup(self) -> None:
        text = SECURITY_TEST.read_text(encoding="utf-8")
        self.assertIn("sudo -v", text)
        self.assertIn("sudo -n", text)
        self.assertNotIn("sudo rm", text)
        self.assertNotIn("sudo env", text)
        self.assertIn("cleanup()", text)
        self.assertIn("trap cleanup EXIT", text)

    def test_denial_path_disables_terminal_agent_and_has_timeout(self) -> None:
        text = SECURITY_TEST.read_text(encoding="utf-8")
        self.assertIn("pkcheck --revoke-temp", text)
        self.assertIn("--disable-internal-agent", text)
        self.assertIn("timeout 60s", text)
        self.assertIn("LC_ALL=C", text)
        self.assertIn("126", text)
        self.assertIn("127", text)
        self.assertIn("Not authorized", text)

    def test_tamper_cases_are_fixed_and_do_not_accept_arbitrary_paths(self) -> None:
        text = SECURITY_TEST.read_text(encoding="utf-8")
        self.assertIn('CORE="$PACKAGE/core.py"', text)
        self.assertIn('PROTOCOL="$PACKAGE/protocol.py"', text)
        self.assertIn('MANIFEST="$TARGET/kill-switch-helper-manifest.json"', text)
        self.assertIn("checksum mismatch", text)
        self.assertIn("mode", text)
        self.assertNotIn("eval ", text)
        self.assertNotIn("rm -rf", text)

    def test_self_test_is_unprivileged(self) -> None:
        text = SELF_TEST.read_text(encoding="utf-8")
        for forbidden in ("sudo ", "pkexec ", "nft ", "nmcli "):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
