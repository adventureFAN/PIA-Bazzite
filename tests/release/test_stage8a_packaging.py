from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.adventurefan.PIABazzite"
EXPECTED_VERSION = "0.7.0"


def load_bundle_builder():
    path = ROOT / "packaging" / "build-helper-bundle.py"
    spec = importlib.util.spec_from_file_location("pia_stage8a_bundle_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Stage8AReleaseMetadataTests(unittest.TestCase):
    def test_active_release_version_is_consistent(self) -> None:
        init_source = (ROOT / "pia_bazzite" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{EXPECTED_VERSION}"', init_source)

        desktop = (ROOT / "packaging" / f"{APP_ID}.desktop").read_text(encoding="utf-8")
        self.assertIn(f"X-AppImage-Version={EXPECTED_VERSION}", desktop)

        tree = ET.parse(ROOT / "packaging" / f"{APP_ID}.metainfo.xml")
        releases = tree.getroot().find("releases")
        self.assertIsNotNone(releases)
        first = list(releases)[0]
        self.assertEqual(first.attrib.get("version"), EXPECTED_VERSION)

        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn(f"body_path: RELEASE_NOTES_{EXPECTED_VERSION}.md", workflow)
        self.assertIn('EXPECTED="v$(python -c', workflow)
        self.assertIn('GITHUB_REF_NAME', workflow)

    def test_active_public_docs_do_not_claim_the_kill_switch_is_missing(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Session Kill Switch", readme)
        self.assertNotIn("currently has **no kill switch**", readme)
        self.assertIn(f"PIA-Bazzite-{EXPECTED_VERSION}-x86_64.AppImage", readme)
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("Session Kill Switch", security)
        self.assertNotIn("currently has no kill switch", security.casefold())
        self.assertTrue((ROOT / f"RELEASE_NOTES_{EXPECTED_VERSION}.md").is_file())

    def test_build_version_is_derived_from_runtime_package(self) -> None:
        build = (ROOT / "packaging" / "build-appimage.sh").read_text(encoding="utf-8")
        self.assertIn("from pia_bazzite import __version__", build)
        self.assertNotIn('VERSION="0.5.0"', build)
        self.assertIn("build-helper-bundle.py", build)
        self.assertIn("kill-switch-helper-bundle", build)


class Stage8AHelperBundleTests(unittest.TestCase):
    def test_builder_creates_exact_versioned_hash_manifest(self) -> None:
        module = load_bundle_builder()
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "bundle"
            manifest_path = module.build_bundle(
                root=ROOT,
                destination=destination,
                version=EXPECTED_VERSION,
            )
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], 1)
            self.assertEqual(document["app_version"], EXPECTED_VERSION)
            self.assertEqual(document["helper_stage"], 5)
            self.assertEqual(document["protocol_version"], 1)
            expected_names = {name for name, _mode in module.BUNDLE_FILES}
            self.assertEqual(set(document["files"]), expected_names)
            for relative, mode in module.BUNDLE_FILES:
                target = destination / relative
                self.assertTrue(target.is_file())
                self.assertFalse(target.is_symlink())
                self.assertEqual(target.stat().st_mode & 0o777, mode)
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                self.assertEqual(document["files"][relative], digest)

    def test_bundle_excludes_development_and_test_helpers(self) -> None:
        module = load_bundle_builder()
        names = {name for name, _mode in module.BUNDLE_FILES}
        self.assertNotIn("helper/pia-bazzite-kill-switch-helper", names)
        self.assertNotIn("helper/pia-bazzite-polkit-probe", names)
        self.assertFalse(any(name.startswith("tests/") for name in names))
        self.assertFalse(any("namespace" in name for name in names))

    def test_bundle_builder_is_network_and_privilege_free(self) -> None:
        source = (ROOT / "packaging" / "build-helper-bundle.py").read_text(encoding="utf-8")
        for forbidden in ("sudo", "pkexec", "nft", "nmcli", "urlopen", "requests"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
