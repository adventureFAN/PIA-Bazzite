from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
WIDGETS = ROOT / "pia_bazzite" / "kill_switch_widgets.py"
RESOURCE_DIR = ROOT / "pia_bazzite" / "resources" / "i18n"
PREVIEW = ROOT / "tools" / "pia-bazzite-stage4c-runtime-preview.py"


class Stage4C1PolishTests(unittest.TestCase):
    def translations(self, language: str) -> dict[str, str]:
        return json.loads(
            (RESOURCE_DIR / f"{language}.json").read_text(encoding="utf-8")
        )

    def test_ready_names_identify_vpn_and_optional_kill_switch(self) -> None:
        de = self.translations("de")
        en = self.translations("en")
        self.assertEqual(de["kill_switch.state.ready"], "VPN bereit")
        self.assertEqual(
            de["kill_switch.state.armed"],
            "VPN & Kill Switch bereit",
        )
        self.assertEqual(en["kill_switch.state.ready"], "VPN ready")
        self.assertEqual(
            en["kill_switch.state.armed"],
            "VPN & kill switch ready",
        )

    def test_protection_error_points_to_live_log_in_visible_summary(self) -> None:
        de = self.translations("de")
        en = self.translations("en")
        self.assertIn("Live-Log", de["kill_switch.summary.error"])
        self.assertIn("Live Log", en["kill_switch.summary.error"])

    def test_every_full_status_tooltip_has_deliberate_line_breaks(self) -> None:
        for language in ("de", "en"):
            translations = self.translations(language)
            for mode in ("ready", "armed", "vpn_only", "active", "blocking", "error"):
                detail = translations[f"kill_switch.detail.{mode}"]
                with self.subTest(language=language, mode=mode):
                    self.assertIn("\n", detail)
                    self.assertLessEqual(
                        max(len(line) for line in detail.splitlines()),
                        94,
                    )

    def test_status_copy_is_lower_and_log_buttons_are_visibly_separated(self) -> None:
        widget_source = WIDGETS.read_text(encoding="utf-8")
        gui_source = GUI.read_text(encoding="utf-8")
        self.assertIn(
            "text_layout.setContentsMargins(0, 14, 0, 0)",
            widget_source,
        )
        self.assertIn(
            "buttons.setContentsMargins(0, 8, 0, 0)",
            gui_source,
        )

    def test_main_window_is_narrower_in_both_modes(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("COMPACT_SIZE = QSize(690, 510)", source)
        self.assertIn("LOG_SIZE = QSize(760, 780)", source)

    def test_runtime_preview_checks_wrapped_tooltips_and_dynamic_log_layout(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        self.assertIn('if "\\n" not in tooltip:', source)
        self.assertIn("expected_size = window._expanded_log_size()", source)
        self.assertIn("window.height() < LOG_SIZE.height()", source)
        self.assertIn("button_top < log_bottom", source)
        self.assertNotIn("window.size() != QSize(760, 780)", source)



if __name__ == "__main__":
    unittest.main()
