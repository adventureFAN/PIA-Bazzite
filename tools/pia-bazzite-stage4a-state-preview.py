#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pia_bazzite.i18n import set_language, tr
from pia_bazzite.icons import status_dot_icon, status_icon
from pia_bazzite.kill_switch_state import (
    KillSwitchViewState,
    sample_kill_switch_states,
    status_color_hex,
)
from pia_bazzite.theme import ThemeController


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the four stage-4 kill-switch UI states without networking."
    )
    parser.add_argument("--language", choices=("en", "de"), default="en")
    parser.add_argument("--theme", choices=("system", "light", "dark"), default="system")
    return parser.parse_args()


def _palette_is_dark(widget: QWidget) -> bool:
    color = widget.palette().color(QPalette.ColorRole.Window)
    luminance = (0.2126 * color.red()) + (0.7152 * color.green()) + (0.0722 * color.blue())
    return luminance < 128


class StateCard(QFrame):
    def __init__(self, state: KillSwitchViewState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(QSize(360, 190))

        self.shield = QLabel()
        self.shield.setFixedSize(68, 68)
        self.shield.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel()
        self.title.setStyleSheet("font-size: 19px; font-weight: 650;")

        self.detail = QLabel()
        self.detail.setWordWrap(True)

        self.tray_dot = QLabel()
        self.tray_dot.setFixedSize(22, 22)
        self.tray_text = QLabel()

        heading = QHBoxLayout()
        heading.addWidget(self.shield)
        heading.addWidget(self.title, 1)

        tray_row = QHBoxLayout()
        tray_row.addWidget(self.tray_dot)
        tray_row.addWidget(self.tray_text, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(heading)
        layout.addWidget(self.detail)
        layout.addStretch()
        layout.addLayout(tray_row)

        self.refresh()

    def refresh(self) -> None:
        dark = _palette_is_dark(self)
        color = status_color_hex(self.state.icon_state, dark_mode=dark)
        self.shield.setPixmap(
            status_icon(self.state.icon_state, 60, palette=self.palette()).pixmap(60, 60)
        )
        self.title.setText(tr(self.state.title_key))
        self.title.setStyleSheet(
            f"font-size: 19px; font-weight: 650; color: {color};"
        )
        self.detail.setText(tr(self.state.detail_key))
        self.tray_dot.setPixmap(
            status_dot_icon(self.state.icon_state, 18, palette=self.palette()).pixmap(18, 18)
        )
        self.tray_text.setText(tr(self.state.tray_status_key))


class PreviewWindow(QMainWindow):
    def __init__(
        self,
        app: QApplication,
        theme_controller: ThemeController,
        *,
        language_code: str,
        theme_mode: str,
    ) -> None:
        super().__init__()
        self.app = app
        self.theme_controller = theme_controller
        self.language_code = language_code
        self.theme_mode = theme_mode
        self.cards: list[StateCard] = []

        self.setWindowTitle("PIA Bazzite — Stage 4A state preview")
        self.setWindowIcon(status_icon("application"))
        self.setMinimumSize(820, 720)

        central = QWidget()
        page = QVBoxLayout(central)
        page.setContentsMargins(18, 16, 18, 16)
        page.setSpacing(12)

        title = QLabel("Kill-switch state preview")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        note = QLabel(
            "Simulation only — this preview does not start the helper, Polkit, "
            "NetworkManager, or nftables."
        )
        note.setWordWrap(True)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Deutsch", "de")
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(language_code))
        )
        self.language_combo.currentIndexChanged.connect(self._change_language)
        controls.addWidget(self.language_combo)

        controls.addSpacing(14)
        controls.addWidget(QLabel("Appearance:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("System", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme_mode)))
        self.theme_combo.currentIndexChanged.connect(self._change_theme)
        controls.addWidget(self.theme_combo)
        controls.addStretch()

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, state in enumerate(sample_kill_switch_states()):
            card = StateCard(state)
            self.cards.append(card)
            grid.addWidget(card, index // 2, index % 2)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        self.log_view.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close_button)

        page.addWidget(title)
        page.addWidget(note)
        page.addLayout(controls)
        page.addLayout(grid)
        page.addWidget(QLabel("Live Log transition preview"))
        page.addWidget(self.log_view)
        page.addLayout(footer)
        self.setCentralWidget(central)
        self._refresh_content()

    def _change_language(self) -> None:
        self.language_code = str(self.language_combo.currentData())
        set_language(self.language_code)
        self._refresh_content()

    def _change_theme(self) -> None:
        self.theme_mode = str(self.theme_combo.currentData())
        self.theme_controller.apply(self.theme_mode)
        self._refresh_content()

    def _refresh_content(self) -> None:
        for card in self.cards:
            card.refresh()
        self.log_view.clear()
        timestamp = datetime.now().strftime("%H:%M:%S")
        for state in sample_kill_switch_states():
            level = tr(f"log.level.{state.log_level}")
            self.log_view.appendPlainText(
                f"{timestamp}  {level:<7}  {tr(state.log_key)}"
            )


def main() -> int:
    args = _arguments()
    set_language(args.language)

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("PIA Bazzite Stage 4A Preview")
    controller = ThemeController(app)
    controller.apply(args.theme)

    window = PreviewWindow(
        app,
        controller,
        language_code=args.language,
        theme_mode=args.theme,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
