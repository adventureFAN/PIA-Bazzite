from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def _load_collector():
    path = ROOT / "packaging" / "collect_third_party_licenses.py"
    spec = importlib.util.spec_from_file_location("pia_stage8c2_license_collector", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeDistribution:
    def __init__(self, base: Path, name: str, version: str, requires=(), files=()):
        self._base = base
        self.metadata = {"Name": name, "Version": version, "License": "MIT"}
        self.version = version
        self.requires = list(requires)
        self.files = [PurePosixPath(value) for value in files]

    def locate_file(self, value):
        return self._base / str(value)


class Stage8C2PackagingHygieneTests(unittest.TestCase):
    def test_stage8d_release_metadata_and_action_pins_are_frozen(self):
        release_date = "2026-08-08"
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [0.6.0] - {release_date}", changelog)

        import xml.etree.ElementTree as ET
        tree = ET.parse(ROOT / "packaging/io.github.adventurefan.PIABazzite.metainfo.xml")
        releases = tree.getroot().find("releases")
        self.assertIsNotNone(releases)
        active = list(releases)[0]
        self.assertEqual(active.attrib.get("version"), "0.6.0")
        self.assertEqual(active.attrib.get("date"), release_date)

        expected_pins = {
            "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
            "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
            "softprops/action-gh-release": "3bb12739c298aeb8a4eeaf626c5b8d85266b0e65",
        }
        for workflow_name in ("ci.yml", "release.yml"):
            workflow = (ROOT / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
            for line in workflow.splitlines():
                stripped = line.strip()
                if not stripped.startswith("- uses:") and not stripped.startswith("uses:"):
                    continue
                use_value = stripped.split("uses:", 1)[1].strip().split()[0]
                owner_action, separator, ref = use_value.partition("@")
                self.assertTrue(separator, use_value)
                self.assertRegex(ref, r"^[0-9a-f]{40}$", use_value)
                self.assertIn(owner_action, expected_pins, use_value)
                self.assertEqual(ref, expected_pins[owner_action], use_value)

    def test_workflows_use_one_authoritative_unprivileged_gate(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        needle = "bash tools/release-unprivileged-gate.sh"
        self.assertIn(needle, ci)
        self.assertIn(needle, release)
        self.assertNotIn("unittest discover -s tests/release", ci)
        self.assertNotIn("unittest discover -s tests/release", release)

    def test_local_release_mode_requires_clean_git_archive_head(self):
        source = (ROOT / "packaging/build-appimage-podman.sh").read_text(encoding="utf-8")
        self.assertIn('BUILD_MODE="${PIA_BAZZITE_BUILD_MODE:-development}"', source)
        self.assertIn('status --porcelain --untracked-files=all', source)
        self.assertIn('git -C "$ROOT" archive --format=tar HEAD', source)
        self.assertIn('SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"', source)

    def test_appimagetool_is_sha256_pinned_before_execution(self):
        source = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        expected = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
        self.assertIn(f'APPIMAGETOOL_SHA256="{expected}"', source)
        self.assertGreaterEqual(source.count("sha256sum --check --status"), 2)
        self.assertLess(source.index("sha256sum --check --status"), source.rindex('"$APPIMAGETOOL" "$APPDIR" "$OUTPUT"'))

    def test_build_embeds_source_identity_and_collects_runtime_licenses(self):
        source = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        self.assertIn("collect_third_party_licenses.py", source)
        self.assertIn("BUILD_INFO.txt", source)
        self.assertIn("Source commit: $SOURCE_COMMIT", source)
        self.assertIn("${APP_ID}.appdata.xml", source)

    def test_pyside_license_texts_are_vendored_pinned_and_packaged(self):
        source = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        expected = {
            "LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
            "GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
            "GPL-2.0.txt": "edaef632cbb643e4e7a221717a6c441a4c1a7c918e6e4d56debc3d8739b233f6",
        }
        import hashlib
        for filename, digest in expected.items():
            path = ROOT / "packaging" / "licenses" / filename
            self.assertTrue(path.is_file(), filename)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertIn(filename, source)
            self.assertIn(digest, source)
        self.assertIn('PYSIDE_LICENSE_DIR="$THIRD_PARTY_DIR/PySide6-Qt"', source)

    def test_release_workflow_anchors_build_info_to_github_sha(self):
        source = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("PIA_BAZZITE_BUILD_MODE: release", source)
        self.assertIn("PIA_BAZZITE_SOURCE_COMMIT: ${{ github.sha }}", source)
        self.assertIn('git reset --hard "$GITHUB_SHA"', source)
        self.assertIn("git clean -ffdx", source)
        self.assertLess(source.index("git clean -ffdx"), source.index("./packaging/build-appimage.sh"))

    def test_ci_installs_runtime_before_full_authoritative_gate(self):
        source = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python -m pip install -r requirements.txt", source)
        self.assertLess(source.index("python -m pip install -r requirements.txt"), source.index("bash tools/release-unprivileged-gate.sh"))

    def test_direct_release_build_requires_clean_exact_source_identity(self):
        source = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        self.assertIn('if [[ "$BUILD_MODE" == "release" ]]', source)
        self.assertIn('status --porcelain --untracked-files=all', source)
        self.assertIn('requested release source commit does not match checked-out HEAD', source)
        self.assertIn('release mode without Git metadata requires an exact hexadecimal source commit', source)

    def test_packaging_host_gate_is_unprivileged_and_inspects_real_artifact(self):
        source = (ROOT / "tools/release-stage8c2-packaging-host-test.sh").read_text(encoding="utf-8")
        self.assertIn("build-appimage-podman.sh", source)
        self.assertIn("--appimage-extract", source)
        self.assertIn("BUILD_INFO.txt", source)
        self.assertIn("third-party-python/COMPONENTS.txt", source)
        for forbidden in ("\nsudo ", "\npkexec ", "\nnmcli ", "\nnft "):
            self.assertNotIn(forbidden, source)

    def test_license_collector_recurses_and_copies_only_license_material(self):
        module = _load_collector()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "installed"
            dest = Path(tmp) / "out"
            root_license = base / "Root-1.dist-info/licenses/LICENSE"
            root_code = base / "root_pkg/code.py"
            child_notice = base / "Child-2.dist-info/NOTICE.txt"
            for path, content in (
                (root_license, "root license"),
                (root_code, "print('not a license')"),
                (child_notice, "child notice"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            dists = {
                "root": _FakeDistribution(
                    base,
                    "Root",
                    "1",
                    requires=["Child>=2; python_version >= '3.0'"],
                    files=["Root-1.dist-info/licenses/LICENSE", "root_pkg/code.py"],
                ),
                "child": _FakeDistribution(
                    base,
                    "Child",
                    "2",
                    files=["Child-2.dist-info/NOTICE.txt"],
                ),
            }

            def get_dist(name: str):
                key = module.normalize_name(name)
                if key not in dists:
                    raise module.metadata.PackageNotFoundError(name)
                return dists[key]

            components = module.collect_runtime_licenses(dest, roots=("Root",), distribution_getter=get_dist)
            self.assertEqual([item[0] for item in components], ["Child", "Root"])
            copied_text = "\n".join(str(path.relative_to(dest)) for path in dest.rglob("*") if path.is_file())
            self.assertIn("LICENSE", copied_text)
            self.assertIn("NOTICE.txt", copied_text)
            self.assertNotIn("code.py", copied_text)
            manifest = (dest / "COMPONENTS.txt").read_text(encoding="utf-8")
            self.assertIn("Root 1", manifest)
            self.assertIn("Child 2", manifest)

    def test_public_docs_describe_generated_license_inventory_and_no_stage8_release_copy(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        notes = (ROOT / "RELEASE_NOTES_0.6.0.md").read_text(encoding="utf-8")
        self.assertIn("third-party-python/COMPONENTS.txt", notices)
        self.assertIn("Qt/PySide6", notices)
        self.assertNotIn("Stage 8 validates", notes)


if __name__ == "__main__":
    unittest.main()
