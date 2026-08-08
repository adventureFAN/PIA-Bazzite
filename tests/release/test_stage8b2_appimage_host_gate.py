from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Stage8B2PackagingTests(unittest.TestCase):
    def test_checksum_sidecar_is_portable(self) -> None:
        build = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        self.assertIn('cd "$DIST_DIR"', build)
        self.assertIn('sha256sum "$(basename "$OUTPUT")"', build)
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn('(cd dist && sha256sum "$(basename "$APPIMAGE")"', workflow)

    def test_podman_build_stages_source_before_selinux_relabel(self) -> None:
        source = (ROOT / "packaging/build-appimage-podman.sh").read_text(encoding="utf-8")
        self.assertNotIn('-v "$ROOT:/workspace:Z"', source)
        self.assertIn('STAGE_ROOT="$(mktemp -d', source)
        self.assertIn('-v "$WORKSPACE:/workspace:Z"', source)
        self.assertIn("--exclude='*/__pycache__'", source)
        self.assertIn("--exclude='*.pyc'", source)
        self.assertIn("--exclude='./test-results'", source)
        self.assertIn('cp -f "$artifact" "$ROOT/dist/$(basename "$artifact")"', source)

    def test_inspector_uses_exact_packaged_helper_contract(self) -> None:
        source = (ROOT / "tools/pia-bazzite-stage8b2-appimage-inspector.py").read_text(encoding="utf-8")
        self.assertIn("BUNDLE_SOURCE_MODES", source)
        self.assertIn("EXPECTED_HELPER_STAGE", source)
        self.assertIn("EXPECTED_PROTOCOL_VERSION", source)
        self.assertIn("PackagedHelperManager", source)
        self.assertIn('choices=("bundle", "audit-installed", "snapshot-installed")', source)

    def test_host_gate_proves_fuse_bundle_staging_before_helper_mutation(self) -> None:
        source = (ROOT / "tools/release-stage8b2-host-test.sh").read_text(encoding="utf-8")
        staging = source.index("Prove the normal AppImage bundle can be staged for root")
        uninstall = source.index('pia-bazzite-stage2-helper-installer.sh\" uninstall')
        self.assertLess(staging, uninstall)
        self.assertIn("env -u APPIMAGE_EXTRACT_AND_RUN", source)
        self.assertIn("manager._stage_verified_bundle(manifest)", source)
        self.assertIn('"/usr/bin/sudo", "-n", "/usr/bin/test", "-r"', source)
        self.assertIn("normal FUSE permission model", source)

    def test_mount_discovery_is_scoped_to_started_appimage_session_and_skips_proc_denials(self) -> None:
        source = (ROOT / "tools/release-stage8b2-host-test.sh").read_text(encoding="utf-8")
        self.assertIn('done < <(ps -eo pid=,sid=)', source)
        self.assertIn('[[ "$proc_sid" == "$APP_PID" ]] || continue', source)
        self.assertIn("{ tr '\\0' '\\n' < \"$proc_environ\"; } 2>/dev/null", source)
        self.assertIn('|| true', source)
        self.assertNotIn('for proc in /proc/[0-9]*', source)

    def test_host_gate_orders_missing_current_outdated_without_vpn_connect(self) -> None:
        source = (ROOT / "tools/release-stage8b2-host-test.sh").read_text(encoding="utf-8")
        missing = source.index("Missing helper: install from the real AppImage")
        current = source.index("Current helper: exact AppImage must not reinstall it")
        outdated = source.index("Outdated helper metadata: AppImage must require an explicit update")
        self.assertLess(missing, current)
        self.assertLess(current, outdated)
        self.assertNotIn("connection up", source)
        self.assertNotIn("nft add", source)
        self.assertNotIn("nft create", source)
        self.assertIn("Do NOT connect the VPN", source)

    def test_failure_path_restores_helper_only_on_clean_host(self) -> None:
        source = (ROOT / "tools/release-stage8b2-host-test.sh").read_text(encoding="utf-8")
        self.assertIn("attempting safe source-tree helper restoration", source)
        self.assertIn("if ! sudo \"$NFT_BIN\" list table", source)
        self.assertIn('pia-bazzite-stage2-helper-installer.sh\" install', source)
        restore = (ROOT / "tools/release-stage8b2-emergency-restore.sh").read_text(encoding="utf-8")
        self.assertIn("Use the Stage-7D Emergency Reset instead", restore)


if __name__ == "__main__":
    unittest.main()
