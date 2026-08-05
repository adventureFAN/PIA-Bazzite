from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE = PROJECT_ROOT / "helper" / "pia-bazzite-polkit-probe"


class ProbeTests(unittest.TestCase):
    def run_probe(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PROBE), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )

    def test_invalid_action_is_rejected_before_privilege_check(self) -> None:
        result = self.run_probe("not-an-action")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("pkexec", result.stderr.lower())

    def test_unprivileged_status_does_not_claim_success(self) -> None:
        result = self.run_probe("status")
        self.assertEqual(result.returncode, 3)
        payload = json.loads(result.stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "privilege")

    def test_probe_contains_no_network_or_nftables_execution(self) -> None:
        text = PROBE.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])

        forbidden_modules = {"subprocess", "socket", "urllib", "requests", "http", "asyncio"}
        self.assertTrue(imported.isdisjoint(forbidden_modules), imported & forbidden_modules)
        self.assertNotIn("/usr/bin/nft", text)
        self.assertNotIn("/usr/sbin/nft", text)
        self.assertNotIn("nmcli", text)
        self.assertNotIn("NetworkManager", text)

    def test_fixed_install_path_is_literal(self) -> None:
        text = PROBE.read_text(encoding="utf-8")
        self.assertIn(
            '/usr/local/libexec/pia-bazzite/pia-bazzite-auth-probe',
            text,
        )
        self.assertNotIn("os.environ.get(\"PATH\"", text)


if __name__ == "__main__":
    unittest.main()
