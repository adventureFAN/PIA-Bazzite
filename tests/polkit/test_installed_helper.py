from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helper.pia_bazzite_kill_switch_helper import installed_entry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_SOURCE = PROJECT_ROOT / "helper" / "pia-bazzite-kill-switch-helper-installed"
INSTALLER = PROJECT_ROOT / "tools" / "pia-bazzite-stage2-helper-installer.sh"


class InstalledBoundaryTests(unittest.TestCase):
    def _temporary_install(self, root: Path) -> tuple[Path, Path]:
        package = root / "pia_bazzite_kill_switch_helper"
        package.mkdir(parents=True)
        for relative in installed_entry.EXPECTED_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        manifest = root / "kill-switch-helper-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "install_format": installed_entry.INSTALL_FORMAT,
                    "helper_stage": 2,
                    "protocol_version": 1,
                    "files": {name: "a" * 64 for name in installed_entry.EXPECTED_FILES},
                }
            ),
            encoding="utf-8",
        )
        return root / "pia-bazzite-kill-switch-helper", manifest

    def test_fixed_install_tree_and_manifest_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pia-bazzite"
            launcher, manifest = self._temporary_install(root)
            with patch.object(installed_entry, "_verify_safe_directory"), \
                    patch.object(installed_entry, "_verify_safe_file"), \
                    patch.object(installed_entry, "_sha256", return_value="a" * 64):
                result = installed_entry.verify_installation(
                    launcher,
                    install_root=root,
                    installed_launcher=launcher,
                    manifest_path=manifest,
                )
        self.assertEqual(set(result), set(installed_entry.EXPECTED_FILES))

    def test_wrong_manifest_identity_is_rejected(self) -> None:
        for field, value in (
            ("install_format", 999),
            ("helper_stage", 999),
            ("protocol_version", 999),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "pia-bazzite"
                launcher, manifest = self._temporary_install(root)
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                payload[field] = value
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                with patch.object(installed_entry, "_verify_safe_directory"), \
                        patch.object(installed_entry, "_verify_safe_file"):
                    with self.assertRaises(installed_entry.InstallationBoundaryError):
                        installed_entry.verify_installation(
                            launcher,
                            install_root=root,
                            installed_launcher=launcher,
                            manifest_path=manifest,
                        )

    def test_unexpected_manifest_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pia-bazzite"
            launcher, manifest = self._temporary_install(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["unexpected"] = True
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(installed_entry, "_verify_safe_directory"), \
                    patch.object(installed_entry, "_verify_safe_file"):
                with self.assertRaises(installed_entry.InstallationBoundaryError):
                    installed_entry.verify_installation(
                        launcher,
                        install_root=root,
                        installed_launcher=launcher,
                        manifest_path=manifest,
                    )

    def test_launcher_outside_fixed_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pia-bazzite"
            launcher, manifest = self._temporary_install(root)
            wrong = root.parent / "user-controlled-helper"
            wrong.write_text("wrong", encoding="utf-8")
            with self.assertRaises(installed_entry.InstallationBoundaryError):
                installed_entry.verify_installation(
                    wrong,
                    install_root=root,
                    installed_launcher=launcher,
                    manifest_path=manifest,
                )

    @patch("helper.pia_bazzite_kill_switch_helper.installed_entry.os.geteuid", return_value=1000)
    def test_non_root_execution_is_rejected(self, geteuid) -> None:
        with self.assertRaises(installed_entry.AuthorizationBoundaryError):
            installed_entry.verify_pkexec_authorization({"PKEXEC_UID": "1000"})

    @patch("helper.pia_bazzite_kill_switch_helper.installed_entry.os.geteuid", return_value=0)
    def test_missing_or_root_pkexec_uid_is_rejected(self, geteuid) -> None:
        for environment in ({}, {"PKEXEC_UID": "root"}, {"PKEXEC_UID": "0"}):
            with self.subTest(environment=environment), \
                    self.assertRaises(installed_entry.AuthorizationBoundaryError):
                installed_entry.verify_pkexec_authorization(environment)

    @patch("helper.pia_bazzite_kill_switch_helper.installed_entry.os.geteuid", return_value=0)
    def test_non_root_pkexec_uid_is_accepted(self, geteuid) -> None:
        self.assertEqual(installed_entry.verify_pkexec_authorization({"PKEXEC_UID": "1000"}), 1000)

    def test_environment_is_reduced_to_fixed_values(self) -> None:
        original = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({"LD_PRELOAD": "/tmp/evil.so", "PYTHONPATH": "/tmp/evil"})
            installed_entry.sanitize_environment(1000)
            self.assertEqual(
                dict(os.environ),
                {
                    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                    "LC_ALL": "C",
                    "PKEXEC_UID": "1000",
                },
            )
        finally:
            os.environ.clear()
            os.environ.update(original)


class InstalledFilesStaticTests(unittest.TestCase):
    def test_launcher_verifies_before_importing_installed_package(self) -> None:
        text = LAUNCHER_SOURCE.read_text(encoding="utf-8")
        verify_call = text.index("_verify_installation()")
        package_import = text.index("from pia_bazzite_kill_switch_helper.installed_entry")
        self.assertLess(verify_call, package_import)
        prefix = text[:package_import]
        self.assertNotIn("from pia_bazzite_kill_switch_helper", prefix)
        self.assertNotIn("import pia_bazzite_kill_switch_helper", prefix)

    def test_launcher_bootstrap_has_fixed_scope_and_isolated_python(self) -> None:
        text = LAUNCHER_SOURCE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/python3 -I\n"))
        self.assertIn("/usr/local/libexec/pia-bazzite", text)
        self.assertIn("EXPECTED_FILES", text)
        self.assertIn("Installed helper checksum mismatch", text)
        self.assertNotIn("subprocess", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("eval(", text)

    def test_installer_has_fixed_scope_lock_and_preflight_uninstall(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('TARGET_DIR="/usr/local/libexec/pia-bazzite"', text)
        self.assertIn('TARGET_LAUNCHER="$TARGET_DIR/pia-bazzite-kill-switch-helper"', text)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("eval ", text)
        self.assertNotIn("INSTALL_ROOT=", text)
        self.assertNotIn("TARGET_DIR=${", text)
        self.assertIn("protocol.py", text)
        self.assertIn("install_format", text)
        self.assertIn("helper_stage", text)
        self.assertIn("protocol_version", text)
        self.assertIn("flock -n", text)
        self.assertIn("preflight_uninstall", text)
        self.assertLess(text.index("preflight_uninstall\n"), text.index('remove_regular_root_file "$TARGET_LAUNCHER"'))


if __name__ == "__main__":
    unittest.main()
