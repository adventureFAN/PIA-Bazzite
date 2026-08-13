from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"


class Stage7B3LightIconContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.options = OPTIONS.read_text(encoding="utf-8")

    def test_auto_connect_special_icons_follow_the_dialog_palette(self) -> None:
        self.assertIn("def _auto_connect_palette_icon", self.options)
        self.assertIn("self.auto_connect_combo.palette()", self.options)
        self.assertIn("QPalette.ColorRole.Text", self.options)
        self.assertIn("QPalette.ColorRole.HighlightedText", self.options)
        self.assertIn("QPalette.ColorGroup.Disabled", self.options)
        self.assertIn("QIcon.Mode.Selected", self.options)
        self.assertIn("QIcon.Mode.Disabled", self.options)

    def test_last_selected_icon_no_longer_depends_on_desktop_theme_pixels(self) -> None:
        start = self.options.index("    def _auto_connect_mode_icon")
        end = self.options.index("    @staticmethod\n    def _region_ping_sort_key", start)
        block = self.options[start:end]
        self.assertNotIn("QIcon.fromTheme", block)
        self.assertIn("painter.drawArc", block)
        self.assertIn("Last-selected repeat/history glyph", block)

    def test_favorite_gold_is_preserved_while_neutral_modes_are_palette_aware(self) -> None:
        self.assertIn('AUTO_CONNECT_ACCENT_COLOR = "#f4c542"', self.options)
        self.assertIn('self._auto_connect_marker_icon("★", accent=True)', self.options)
        self.assertIn('self._auto_connect_marker_icon("⚡", accent=False)', self.options)
        self.assertIn('self._auto_connect_mode_icon("off")', self.options)
        self.assertIn('self._auto_connect_mode_icon("last")', self.options)


if __name__ == "__main__":
    unittest.main()
