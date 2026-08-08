from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from pia_bazzite.helper_installation import (
    BUNDLE_ENVIRONMENT_KEY,
    BUNDLE_SOURCE_MODES,
    BASH_PATH,
    PYTHON_PATH,
    ROOT_STAGING_BOOTSTRAP,
    HelperInstallationAuthorizationDenied,
    HelperInstallationError,
    HelperInstallationState,
    INSTALLED_MODES,
    PackagedHelperManager,
    SOURCE_TO_INSTALLED,
    InstallerResult,
)

ROOT = Path(__file__).resolve().parents[2]


def load_bundle_builder():
    path = ROOT / "packaging" / "build-helper-bundle.py"
    spec = importlib.util.spec_from_file_location("pia_stage8b_bundle_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_bundle(destination: Path) -> Path:
    builder = load_bundle_builder()
    builder.build_bundle(root=ROOT, destination=destination, version="0.6.0")
    return destination


def install_exact_bundle(bundle: Path, install_root: Path) -> None:
    install_root.parent.mkdir(parents=True, exist_ok=True)
    install_root.parent.chmod(0o755)
    install_root.mkdir(parents=True, exist_ok=True)
    install_root.chmod(0o755)
    package = install_root / "pia_bazzite_kill_switch_helper"
    package.mkdir(parents=True, exist_ok=True)
    package.chmod(0o755)

    bundle_manifest = json.loads((bundle / "bundle-manifest.json").read_text())
    installed_hashes: dict[str, str] = {}
    for source, target in SOURCE_TO_INSTALLED.items():
        destination = install_root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.chmod(0o755)
        shutil.copyfile(bundle / source, destination)
        destination.chmod(INSTALLED_MODES[target])
        installed_hashes[target] = bundle_manifest["files"][source]
    manifest = {
        "schema_version": 1,
        "install_format": 1,
        "helper_stage": 5,
        "protocol_version": 1,
        "files": installed_hashes,
    }
    path = install_root / "kill-switch-helper-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    path.chmod(0o644)


def make_fake_pkexec(path: Path) -> Path:
    path.write_text("#!/usr/bin/env sh\nexit 1\n")
    path.chmod(0o755)
    return path


class FakeRunner:
    def __init__(self, callback=None, returncode: int = 0) -> None:
        self.callback = callback
        self.returncode = returncode
        self.calls: list[tuple[list[str], float, dict[str, str]]] = []

    def run(self, arguments, *, timeout, environment):
        self.calls.append((list(arguments), timeout, dict(environment)))
        if self.callback is not None:
            self.callback()
        return InstallerResult(self.returncode, "installer output", "")


class Stage8BHelperAuditTests(unittest.TestCase):
    def manager(self, *, bundle: Path, install_root: Path, runner=None) -> PackagedHelperManager:
        return PackagedHelperManager(
            bundle_path=bundle,
            install_root=install_root,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            runner=runner,
            environment={
                "PATH": "/tmp/unsafe",
                "PIA_BAZZITE_HELPER_BUNDLE": str(bundle),
                "LD_PRELOAD": "/tmp/evil.so",
                "LANG": "C.UTF-8",
            },
        )

    def test_missing_exact_and_outdated_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            manager = self.manager(bundle=bundle, install_root=install_root)
            self.assertEqual(manager.audit().state, HelperInstallationState.MISSING)

            install_exact_bundle(bundle, install_root)
            self.assertEqual(manager.audit().state, HelperInstallationState.CURRENT)

            target = install_root / "pia_bazzite_kill_switch_helper/core.py"
            target.write_text(target.read_text() + "\n# simulated older helper\n")
            self.assertEqual(manager.audit().state, HelperInstallationState.OUTDATED)

    def test_root_boundary_shape_problems_are_unsafe_not_upgradeable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            install_exact_bundle(bundle, install_root)
            target = install_root / "pia-bazzite-kill-switch-session"
            target.unlink()
            target.symlink_to("pia-bazzite-kill-switch-helper")
            audit = self.manager(bundle=bundle, install_root=install_root).audit()
            self.assertEqual(audit.state, HelperInstallationState.UNSAFE)
            self.assertFalse(audit.installable)

    def test_tampered_bundle_is_rejected_before_installed_helper_is_considered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            install_exact_bundle(bundle, install_root)
            source = bundle / "helper/pia_bazzite_kill_switch_helper/core.py"
            source.write_text(source.read_text() + "\n# tamper\n")
            audit = self.manager(bundle=bundle, install_root=install_root).audit()
            self.assertEqual(audit.state, HelperInstallationState.BUNDLE_INVALID)
            self.assertFalse(audit.current)

    def test_source_tree_mode_remains_unmanaged(self) -> None:
        audit = PackagedHelperManager(bundle_path=None).audit()
        self.assertEqual(audit.state, HelperInstallationState.UNMANAGED_SOURCE)
        self.assertTrue(audit.current)
        self.assertFalse(audit.packaged)


class Stage8BInstallFlowTests(unittest.TestCase):
    def test_install_uses_fixed_pkexec_python_handoff_and_rechecks_exact_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            runner = FakeRunner()

            def install_from_staged_bundle() -> None:
                argv = runner.calls[-1][0]
                staged_bundle = Path(argv[-3])
                self.assertTrue(staged_bundle.is_dir())
                self.assertTrue(str(staged_bundle).startswith("/tmp/pia-bazzite-helper-install-"))
                self.assertTrue((staged_bundle / "bundle-manifest.json").is_file())
                self.assertEqual(
                    (staged_bundle / "bundle-manifest.json").read_bytes(),
                    (bundle / "bundle-manifest.json").read_bytes(),
                )
                install_exact_bundle(bundle, install_root)

            runner.callback = install_from_staged_bundle
            fake_pkexec = make_fake_pkexec(base / "pkexec")
            manager = PackagedHelperManager(
                bundle_path=bundle,
                pkexec_path=fake_pkexec,
                install_root=install_root,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
                runner=runner,
                environment={
                    "PATH": "/tmp/unsafe",
                    BUNDLE_ENVIRONMENT_KEY: str(bundle),
                    "LD_PRELOAD": "/tmp/evil.so",
                    "PKEXEC_UID": "4242",
                    "LANG": "C.UTF-8",
                },
            )
            with mock.patch(
                "pia_bazzite.helper_installation._verify_fixed_executable"
            ) as verify_executable:
                result = manager.install_or_upgrade()
            verify_executable.assert_any_call(fake_pkexec, "pkexec executable")
            verify_executable.assert_any_call(BASH_PATH, "bash executable")
            verify_executable.assert_any_call(
                PYTHON_PATH, "python executable", allow_safe_symlink=True
            )
            self.assertEqual(result.state, HelperInstallationState.CURRENT)
            self.assertEqual(len(runner.calls), 1)
            argv, _timeout, environment = runner.calls[0]
            self.assertEqual(argv[0], str(fake_pkexec))
            self.assertEqual(argv[1], "--disable-internal-agent")
            self.assertEqual(argv[2], str(PYTHON_PATH))
            self.assertEqual(argv[3:5], ["-I", "-c"])
            self.assertEqual(argv[5], ROOT_STAGING_BOOTSTRAP)
            staged_bundle = Path(argv[-3])
            self.assertFalse(staged_bundle.exists())
            self.assertRegex(argv[-2], r"^[0-9a-f]{64}$")
            self.assertEqual(argv[-1], "0.6.0")
            self.assertEqual(environment["PATH"], "/usr/sbin:/usr/bin:/sbin:/bin")
            self.assertNotIn(BUNDLE_ENVIRONMENT_KEY, environment)
            self.assertNotIn("LD_PRELOAD", environment)
            self.assertNotIn("PKEXEC_UID", environment)

    def test_privileged_source_is_private_normal_filesystem_staging_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            runner = FakeRunner(returncode=126)
            fake_pkexec = make_fake_pkexec(base / "pkexec")
            manager = PackagedHelperManager(
                bundle_path=bundle,
                install_root=install_root,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
                pkexec_path=fake_pkexec,
                runner=runner,
            )
            with mock.patch(
                "pia_bazzite.helper_installation._verify_fixed_executable"
            ):
                with self.assertRaises(HelperInstallationAuthorizationDenied):
                    manager.install_or_upgrade()
            argv = runner.calls[0][0]
            staged_bundle = Path(argv[-3])
            self.assertTrue(str(staged_bundle).startswith("/tmp/pia-bazzite-helper-install-"))
            self.assertFalse(staged_bundle.exists())
            self.assertTrue((bundle / "bundle-manifest.json").is_file())

    def test_cancelled_polkit_is_distinct_and_does_not_fake_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            fake_pkexec = make_fake_pkexec(base / "pkexec")
            manager = PackagedHelperManager(
                bundle_path=bundle,
                install_root=install_root,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
                pkexec_path=fake_pkexec,
                runner=FakeRunner(returncode=126),
            )
            with mock.patch(
                "pia_bazzite.helper_installation._verify_fixed_executable"
            ) as verify_executable:
                with self.assertRaises(HelperInstallationAuthorizationDenied):
                    manager.install_or_upgrade()
            verify_executable.assert_any_call(fake_pkexec, "pkexec executable")
            verify_executable.assert_any_call(BASH_PATH, "bash executable")
            verify_executable.assert_any_call(
                PYTHON_PATH, "python executable", allow_safe_symlink=True
            )
            self.assertEqual(manager.audit().state, HelperInstallationState.MISSING)

    def test_user_owned_fake_pkexec_is_rejected_before_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = make_bundle(base / "bundle")
            install_root = base / "local" / "libexec" / "pia-bazzite"
            fake_pkexec = make_fake_pkexec(base / "pkexec")
            if os.geteuid() == 0:
                os.chown(fake_pkexec, 65534, 65534)
            runner = FakeRunner()
            manager = PackagedHelperManager(
                bundle_path=bundle,
                install_root=install_root,
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
                pkexec_path=fake_pkexec,
                runner=runner,
            )
            with self.assertRaisesRegex(HelperInstallationError, "not owned by root:root"):
                manager.install_or_upgrade()
            self.assertEqual(runner.calls, [])


class Stage8BStaticIntegrationTests(unittest.TestCase):
    def test_runtime_and_builder_share_the_exact_payload_contract(self) -> None:
        builder = load_bundle_builder()
        self.assertEqual(dict(builder.BUNDLE_FILES), dict(BUNDLE_SOURCE_MODES))

    def test_runtime_defaults_to_fixed_system_authorization_binaries(self) -> None:
        source = (ROOT / "pia_bazzite/helper_installation.py").read_text(encoding="utf-8")
        self.assertIn('PKEXEC_PATH = Path("/usr/bin/pkexec")', source)
        self.assertIn('BASH_PATH = Path("/usr/bin/bash")', source)
        self.assertIn('PYTHON_PATH = Path("/usr/bin/python3")', source)
        self.assertIn('"--disable-internal-agent"', source)
        self.assertIn("ROOT_STAGING_BOOTSTRAP", source)
        self.assertIn("shell=False", source)

    def test_appimage_exports_only_the_fixed_bundle_location_to_the_gui(self) -> None:
        build = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        self.assertIn(
            'export PIA_BAZZITE_HELPER_BUNDLE="$APPDIR/usr/share/pia-bazzite/kill-switch-helper-bundle"',
            build,
        )
        client = (ROOT / "pia_bazzite/kill_switch_client.py").read_text(encoding="utf-8")
        self.assertIn('"PIA_BAZZITE_HELPER_BUNDLE"', client)

    def test_gui_gates_both_first_enable_and_startup_recovery(self) -> None:
        source = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertIn("PackagedHelperManager.from_environment()", source)
        self.assertIn("_ensure_packaged_kill_switch_helper", source)
        startup = source.index("def _reconcile_kill_switch_startup")
        startup_session = source.index("session = KillSwitchSessionClient", startup)
        startup_gate = source.index("_ensure_packaged_kill_switch_helper", startup)
        self.assertLess(startup_gate, startup_session)
        enable = source.index("def _authorize_kill_switch_preference")
        enable_session = source.index("session = KillSwitchSessionClient", enable)
        enable_gate = source.index("_ensure_packaged_kill_switch_helper", enable)
        self.assertLess(enable_gate, enable_session)

    def test_privileged_installer_requires_explicit_packaged_mode_and_trusted_digest(self) -> None:
        source = (ROOT / "tools/pia-bazzite-stage2-helper-installer.sh").read_text(encoding="utf-8")
        self.assertIn("install-packaged", source)
        self.assertIn("Trusted packaged manifest digest is invalid", source)
        self.assertIn("downgrade to source mode is forbidden", source)
        self.assertIn("Packaged helper source checksum mismatch", source)
        self.assertIn("hashlib.sha256", source)

    def test_root_bootstrap_copies_before_executing_packaged_installer(self) -> None:
        source = ROOT_STAGING_BOOTSTRAP
        self.assertIn('os.O_NOFOLLOW', source)
        self.assertIn('pia-bazzite-helper-root-', source)
        self.assertIn('["/usr/bin/bash", str(installer), "install-packaged", expected_manifest_digest]', source)
        self.assertNotIn('str(source / "tools/pia-bazzite-stage2-helper-installer.sh")', source)

    def test_translations_remain_equal(self) -> None:
        en = json.loads((ROOT / "pia_bazzite/resources/i18n/en.json").read_text())
        de = json.loads((ROOT / "pia_bazzite/resources/i18n/de.json").read_text())
        self.assertEqual(set(en), set(de))
        for key in (
            "kill_switch.helper_install.install_title",
            "kill_switch.helper_install.update_title",
            "error.kill_switch_helper_install.bundle_message",
            "log.kill_switch.helper_install.ready",
        ):
            self.assertIn(key, en)


if __name__ == "__main__":
    unittest.main()
