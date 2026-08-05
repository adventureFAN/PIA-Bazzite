from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / "tools" / "pia-bazzite-stage4a-state-preview.py"
ICONS = ROOT / "pia_bazzite" / "icons.py"
GUI = ROOT / "pia_bazzite" / "gui.py"
RESOURCE_DIR = ROOT / "pia_bazzite" / "resources" / "i18n"

REQUIRED_KEYS = {
    *(f"kill_switch.state.{name}" for name in ("ready", "active", "blocking", "error")),
    *(f"kill_switch.detail.{name}" for name in ("ready", "active", "blocking", "error")),
    *(f"tray.kill_switch_status.{name}" for name in ("ready", "active", "blocking", "error")),
    *(f"tray.kill_switch_tooltip.{name}" for name in ("ready", "active", "blocking", "error")),
    *(f"log.kill_switch.{name}" for name in ("ready", "active", "blocking", "error")),
}


class Stage4AStaticTests(unittest.TestCase):
    def test_preview_has_no_network_or_privileged_imports(self) -> None:
        tree = ast.parse(PREVIEW.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        forbidden = {
            "subprocess",
            "socket",
            "pia_bazzite.network_manager",
            "pia_bazzite.kill_switch_client",
            "pia_bazzite.kill_switch_session",
        }
        self.assertFalse(imports & forbidden)

    def test_preview_uses_only_sample_state_model(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("sample_kill_switch_states", source)
        self.assertNotIn("KillSwitchSessionClient", source)
        self.assertNotIn("network_manager.", source)

    def test_icons_use_shared_state_color_mapping(self) -> None:
        source = ICONS.read_text(encoding="utf-8")
        self.assertIn("from .kill_switch_state import status_color_hex", source)
        self.assertIn('"application": QColor("#2e7d32")', source)
        self.assertIn('"connected": "active"', (ROOT / "pia_bazzite" / "kill_switch_state.py").read_text())

    def test_existing_gui_still_uses_native_tray_menu(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.tray.setContextMenu(menu)", source)
        self.assertNotIn("menu.popup(", source)

    def test_translations_remain_equal_and_contain_stage4_keys(self) -> None:
        english = json.loads((RESOURCE_DIR / "en.json").read_text(encoding="utf-8"))
        german = json.loads((RESOURCE_DIR / "de.json").read_text(encoding="utf-8"))
        self.assertEqual(set(english), set(german))
        self.assertTrue(REQUIRED_KEYS <= set(english))

    def test_preview_bootstraps_project_root_before_package_import(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        root_marker = "PROJECT_ROOT = Path(__file__).resolve().parents[1]"
        path_marker = "sys.path.insert(0, str(PROJECT_ROOT))"
        import_marker = "from pia_bazzite.i18n import set_language, tr"
        self.assertIn(root_marker, source)
        self.assertIn(path_marker, source)
        self.assertLess(source.index(root_marker), source.index(import_marker))
        self.assertLess(source.index(path_marker), source.index(import_marker))

    def test_preview_is_executable_source_with_main_guard(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertTrue(source.startswith("#!/usr/bin/env python3"))
        self.assertIn('if __name__ == "__main__":', source)


if __name__ == "__main__":
    unittest.main()
