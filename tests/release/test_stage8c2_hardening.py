from __future__ import annotations

import base64
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from pia_bazzite import pia_api
from pia_bazzite.helper_installation import PYTHON_PATH, _verify_fixed_executable
from pia_bazzite.models import Region

ROOT = Path(__file__).resolve().parents[2]
VALID_KEY = base64.b64encode(b"k" * 32).decode("ascii")


class Stage8C2PrivacyAndDocsTests(unittest.TestCase):
    def test_public_tree_contains_no_personal_alex_home_or_legacy_org_marker(self) -> None:
        suffixes = {
            ".py", ".sh", ".md", ".json", ".yml", ".yaml", ".toml",
            ".xml", ".desktop", ".spec", ".txt",
        }
        username = "al" + "ex"
        forbidden = (f"/home/{username}", f"/var/home/{username}", "Al" + "exTools")
        hits: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if any(part in {".git", "build", "dist", "test-results"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in forbidden:
                if marker.casefold() in text.casefold():
                    hits.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual(hits, [])

    def test_security_and_living_handoff_document_current_release(self) -> None:
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        handoff = (ROOT / "docs/HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("Session Kill Switch", security)
        self.assertIn("api.country.is", security)
        self.assertIn("Stage 8C", handoff)
        self.assertIn("0.7.x candidates", handoff)
        self.assertIn("trusted networks", handoff)
        self.assertIn("port forwarding", handoff)
        self.assertIn("split tunneling", handoff)

    def test_release_docs_explain_ipv6_policy_and_preserve_project_credits(self) -> None:
        notes = (ROOT / "RELEASE_NOTES_0.6.0.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (notes, readme):
            self.assertIn("IPv6 `AllowedIPs` route", text)
            self.assertIn("native IPv6", text)
            self.assertIn(
                "Project direction, feature design, testing, and release decisions: **adventureFAN**",
                text,
            )
            self.assertIn(
                "Most implementation, debugging, and technical documentation: developed collaboratively with **ChatGPT**",
                text,
            )


class Stage8C2PiaApiTests(unittest.TestCase):
    def test_wireguard_config_is_created_private_from_first_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "piabazzite.conf"
            region = Region(
                region_id="test",
                name="Test",
                meta_ip="198.51.100.10",
                wireguard_ip="198.51.100.20",
                wireguard_hostname="server.example.com",
            )
            payload = {
                "status": "OK",
                "peer_ip": "10.4.3.2/32",
                "server_key": VALID_KEY,
                "server_port": 1337,
                "dns_servers": ["10.0.0.242"],
            }
            credentials = SimpleNamespace(username="user", password="password")
            with mock.patch.object(pia_api, "authenticate", return_value="token"), mock.patch.object(
                pia_api, "_generate_wireguard_keys", return_value=(VALID_KEY, VALID_KEY)
            ), mock.patch.object(pia_api, "_request_wireguard_data", return_value=payload):
                pia_api.create_wireguard_config(
                    config_path=config,
                    credentials=credentials,
                    region=region,
                )
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            text = config.read_text(encoding="utf-8")
            self.assertIn("PrivateKey = ", text)
            self.assertIn("Endpoint = 198.51.100.20:1337", text)

    def test_wireguard_config_refuses_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            victim = base / "victim.txt"
            victim.write_text("keep", encoding="utf-8")
            config = base / "piabazzite.conf"
            config.symlink_to(victim)
            region = Region(
                region_id="test",
                name="Test",
                meta_ip="198.51.100.10",
                wireguard_ip="198.51.100.20",
                wireguard_hostname="server.example.com",
            )
            payload = {
                "status": "OK",
                "peer_ip": "10.4.3.2/32",
                "server_key": VALID_KEY,
                "server_port": 1337,
                "dns_servers": ["10.0.0.242"],
            }
            credentials = SimpleNamespace(username="user", password="password")
            with mock.patch.object(pia_api, "authenticate", return_value="token"), mock.patch.object(
                pia_api, "_generate_wireguard_keys", return_value=(VALID_KEY, VALID_KEY)
            ), mock.patch.object(pia_api, "_request_wireguard_data", return_value=payload):
                with self.assertRaises(pia_api.PiaError):
                    pia_api.create_wireguard_config(
                        config_path=config,
                        credentials=credentials,
                        region=region,
                    )
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

    def test_current_pia_server_list_accepts_single_label_certificate_name(self) -> None:
        payload = {
            "regions": [
                {
                    "id": "fi",
                    "name": "Finland",
                    "geo": False,
                    "servers": {
                        "meta": [{"ip": "198.51.100.10", "cn": "helsinki403"}],
                        "wg": [{"ip": "198.51.100.20", "cn": "helsinki403"}],
                    },
                }
            ]
        }
        response = SimpleNamespace(
            status_code=200,
            text=__import__("json").dumps(payload) + "\nSIGNATURE",
        )
        with mock.patch.object(pia_api.requests, "get", return_value=response):
            regions = pia_api.fetch_regions()
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].wireguard_hostname, "helsinki403")

    def test_single_label_certificate_name_still_rejects_header_injection(self) -> None:
        with self.assertRaises(pia_api.PiaError):
            pia_api._validate_hostname("helsinki403\r\nInjected: yes", "hostname")

    def test_config_forming_values_reject_control_text_and_bad_keys(self) -> None:
        with self.assertRaises(pia_api.PiaError):
            pia_api._validate_hostname("server.example.com\r\nInjected: yes", "hostname")
        with self.assertRaises(pia_api.PiaError):
            pia_api._validate_wireguard_key("not-a-wireguard-key", "key")
        with self.assertRaises(pia_api.PiaError):
            pia_api._validate_port(70000, "port")

    def test_wireguard_http_user_agent_uses_runtime_version(self) -> None:
        source = (ROOT / "pia_bazzite/pia_api.py").read_text(encoding="utf-8")
        self.assertIn('f"User-Agent: PIA-Bazzite/{__version__}', source)
        self.assertNotIn("PIA-Bazzite/0.4", source)


class Stage8C2ImportBoundaryTests(unittest.TestCase):
    def test_i18n_does_not_make_core_modules_require_pyside6_at_import_time(self) -> None:
        import ast

        source = (ROOT / "pia_bazzite/i18n.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        top_level_qt_imports: list[str] = []
        for node in module.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PySide6"):
                top_level_qt_imports.append(node.module or "")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("PySide6"):
                        top_level_qt_imports.append(alias.name)
        self.assertEqual(top_level_qt_imports, [])


class Stage8C2StaticHardeningTests(unittest.TestCase):
    def test_gui_does_not_turn_unknown_networkmanager_state_into_disconnected(self) -> None:
        source = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertIn("NetworkManager status could not be verified", source)
        self.assertIn("network_state_known = False", source)
        self.assertIn("return self.kill_switch_runtime.feature_enabled", source)
        self.assertNotIn("QTimer.singleShot(500, lambda: self.refresh_public_info", source)

    def test_first_run_defers_server_refresh_until_credentials_dialog_finishes(self) -> None:
        source = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertNotIn("QTimer.singleShot(150, self.refresh_regions)", source)
        first_start = source[source.index("    def _first_start"):source.index("    def edit_credentials")]
        self.assertIn("self._request_initial_region_refresh()", first_start)
        gate_start = source.index("    def _request_initial_region_refresh(")
        gate_end = source.index("    def _first_start(", gate_start)
        gate = source[gate_start:gate_end]
        self.assertIn("self._startup_kill_switch_reconciliation_required()", gate)
        self.assertIn("QTimer.singleShot(0, self.refresh_regions)", gate)

    def test_unchecked_public_ip_has_explicit_state_and_live_log_uses_dynamic_height(self) -> None:
        source = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertIn('self.ip_value.setText(tr("status.not_checked"))', source)
        self.assertIn("def _expanded_log_size", source)
        self.assertIn("self.log_panel.minimumSizeHint().height()", source)

    def test_normal_vpn_uses_firewall_guard_not_failed_networkmanager_routes(self) -> None:
        source = (ROOT / "pia_bazzite/network_manager.py").read_text(encoding="utf-8")
        lifecycle = (ROOT / "pia_bazzite/ipv6_guard_lifecycle.py").read_text(encoding="utf-8")
        self.assertIn('"ipv6.method", "disabled"', source)
        self.assertNotIn('type=blackhole', source)
        self.assertNotIn('ipv6_blackhole_active', source)
        self.assertIn('self.session.ipv6_guard_enable()', lifecycle)
        self.assertIn('self.session.ipv6_guard_status()', lifecycle)
        self.assertIn('self.session.ipv6_guard_disable()', lifecycle)
        self.assertIn('self.vpn_backend.disconnect(profile_uuid)', lifecycle)

    def test_networkmanager_postcheck_verifies_ipv4_tunnel_route(self) -> None:
        source = (ROOT / "pia_bazzite/network_manager.py").read_text(encoding="utf-8")
        self.assertIn('"ip", "-4", "route", "get", IPV4_PROBE_TARGET', source)
        self.assertIn('return fields[index + 1] == INTERFACE_NAME', source)
        self.assertGreaterEqual(source.count('if not vpn_ipv4_route_active():'), 2)

    def test_external_host_open_restores_pyinstaller_library_environment(self) -> None:
        source = (ROOT / "pia_bazzite/host_open.py").read_text(encoding="utf-8")
        gui = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertIn('LD_LIBRARY_PATH_ORIG', source)
        self.assertIn('env.pop("LD_LIBRARY_PATH", None)', source)
        self.assertIn('open_host_target(PROJECT_URL)', gui)
        self.assertNotIn('QDesktopServices', gui)

    def test_ui_polish_uses_real_popup_cap_menu_order_and_region_tray_label(self) -> None:
        source = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertIn('class RegionComboBox(QComboBox):', source)
        self.assertIn('popup.setMaximumHeight(height)', source)
        self.assertIn('self.region_combo = RegionComboBox()', source)
        quit_pos = source.index('self.quit_behavior_menu = self.options_menu.addMenu("")')
        kill_pos = source.index('self.options_menu.addAction(self.kill_switch_action)', quit_pos)
        self.assertLess(quit_pos, kill_pos)
        self.assertIn('tray_status_text = tr("tray.status_connected", region=active_name)', source)
        self.assertNotIn('log_folder_button = QPushButton', source)
        self.assertIn('PROJECT_URL = "https://github.com/adventureFAN/PIA-Bazzite"', source)

    def test_intentional_disconnect_suppresses_unverified_periodic_status_flicker(self) -> None:
        source = (ROOT / "pia_bazzite/gui.py").read_text(encoding="utf-8")
        self.assertIn("self._intentional_disconnect_in_progress = False", source)
        self.assertIn("self._intentional_disconnect_in_progress = True", source)
        self.assertIn(
            "if self._intentional_disconnect_in_progress and self._connection_busy and not force:",
            source,
        )
        disconnect = source[source.index("    def disconnect("):source.index("    def _disconnected_kill_switch_may_block") ]
        self.assertGreaterEqual(disconnect.count("self._intentional_disconnect_in_progress = False"), 2)

    def test_network_debug_script_is_read_only_and_redacts_source_addresses(self) -> None:
        source = (ROOT / "tools/pia-bazzite-network-debug.sh").read_text(encoding="utf-8")
        self.assertIn('PIA Bazzite read-only network diagnostic', source)
        self.assertIn('<redacted>', source)
        for forbidden in ('sudo ', 'pkexec ', 'nft ', 'connection modify', 'connection up', 'connection down', 'connection delete'):
            self.assertNotIn(forbidden, source)


    def test_single_instance_serializes_stale_socket_cleanup(self) -> None:
        source = (ROOT / "pia_bazzite/single_instance.py").read_text(encoding="utf-8")
        self.assertIn("QLockFile", source)
        lock = source.index("self._lock.tryLock(0)")
        remove = source.index("QLocalServer.removeServer(self._name)")
        self.assertLess(lock, remove)

    def test_fixed_system_python_boundary_accepts_only_safe_root_interpreter(self) -> None:
        # Fedora/Bazzite normally exposes /usr/bin/python3 as a root-owned
        # symlink to the versioned interpreter.  The privilege handoff must
        # accept that standard root-protected layout without permitting
        # arbitrary user-controlled symlinks.
        _verify_fixed_executable(
            PYTHON_PATH, "python executable", allow_safe_symlink=True
        )

    def test_packaged_helper_handoff_never_executes_user_owned_installer(self) -> None:
        runtime = (ROOT / "pia_bazzite/helper_installation.py").read_text(encoding="utf-8")
        installer = (ROOT / "tools/pia-bazzite-stage2-helper-installer.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHON_PATH = Path("/usr/bin/python3")', runtime)
        self.assertIn("pia-bazzite-helper-root-", runtime)
        self.assertIn("os.O_NOFOLLOW", runtime)
        self.assertIn('"install-packaged"', runtime)
        self.assertIn("downgrade to source mode is forbidden", installer)
        self.assertIn("Trusted packaged manifest digest is invalid", installer)


if __name__ == "__main__":
    unittest.main()
