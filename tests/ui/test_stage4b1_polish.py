from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
WIDGETS = ROOT / "pia_bazzite" / "kill_switch_widgets.py"
PREVIEW = ROOT / "tools" / "pia-bazzite-stage4b-main-window-preview.py"


class Stage4B1PolishStaticTests(unittest.TestCase):
    def test_tooltip_cannot_inherit_title_font_or_color_stylesheet(self) -> None:
        source = WIDGETS.read_text(encoding="utf-8")
        self.assertNotIn("self.title_label.setStyleSheet", source)
        self.assertIn("title_font.setPixelSize(20)", source)
        self.assertIn("title_palette.setColor", source)
        self.assertIn("QPalette.ColorRole.WindowText", source)
        self.assertIn("QColor(color)", source)

    def test_status_copy_is_tighter_and_aligned_with_icon_top(self) -> None:
        source = WIDGETS.read_text(encoding="utf-8")
        self.assertIn("text_layout.setContentsMargins(0, 10, 0, 0)", source)
        self.assertIn("text_layout.setSpacing(1)", source)
        self.assertIn("text_layout.setAlignment(Qt.AlignmentFlag.AlignTop)", source)
        self.assertGreaterEqual(
            source.count("QSizePolicy.Policy.Maximum"),
            2,
        )

    def test_public_ip_refresh_control_is_compact(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("self.ip_refresh_button = QToolButton()", source)
        self.assertIn('self.ip_refresh_button.setText("↻")', source)
        self.assertIn("self.ip_refresh_button.setFixedSize(28, 24)", source)

    def test_main_window_width_is_reduced_without_height_change(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn("COMPACT_SIZE = QSize(760, 510)", source)
        self.assertIn("LOG_SIZE = QSize(800, 780)", source)

    def test_live_log_wraps_and_has_no_horizontal_scrollbar(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        self.assertIn(
            "QPlainTextEdit.LineWrapMode.WidgetWidth",
            source,
        )
        self.assertIn(
            "QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere",
            source,
        )
        self.assertIn(
            "Qt.ScrollBarPolicy.ScrollBarAlwaysOff",
            source,
        )
        self.assertNotIn(
            "self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)",
            source,
        )
        self.assertIn("buttons.setContentsMargins(0, 2, 0, 0)", source)

    def test_runtime_smoke_probe_checks_polished_controls(self) -> None:
        source = PREVIEW.read_text(encoding="utf-8")
        for expected in (
            "window.log_view.lineWrapMode()",
            "window.log_view.horizontalScrollBarPolicy()",
            "window.ip_refresh_button.size()",
            "window.size()",
        ):
            self.assertIn(expected, source)


if __name__ == "__main__":
    unittest.main()
