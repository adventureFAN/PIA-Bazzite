from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class ThemeController:
    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._system_palette = QPalette(app.palette())

    def apply(self, mode: str) -> bool:
        mode = mode if mode in {"system", "light", "dark"} else "system"
        hints = self._app.styleHints()

        if hasattr(hints, "setColorScheme") and hasattr(Qt, "ColorScheme"):
            scheme = {
                "system": Qt.ColorScheme.Unknown,
                "light": Qt.ColorScheme.Light,
                "dark": Qt.ColorScheme.Dark,
            }[mode]
            hints.setColorScheme(scheme)
            if mode == "system":
                self._app.setPalette(self._system_palette)
            return True

        if mode == "system":
            self._app.setPalette(self._system_palette)
            return True

        palette = QPalette()
        if mode == "dark":
            palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 45))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(238, 238, 238))
            palette.setColor(QPalette.ColorRole.Base, QColor(32, 32, 32))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(238, 238, 238))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(25, 25, 25))
            palette.setColor(QPalette.ColorRole.Text, QColor(238, 238, 238))
            palette.setColor(QPalette.ColorRole.Button, QColor(52, 52, 52))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(238, 238, 238))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("red"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(140, 140, 140))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(140, 140, 140))
        else:
            palette.setColor(QPalette.ColorRole.Window, QColor(246, 246, 246))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(20, 20, 20))
            palette.setColor(QPalette.ColorRole.Base, QColor("white"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(20, 20, 20))
            palette.setColor(QPalette.ColorRole.Text, QColor(20, 20, 20))
            palette.setColor(QPalette.ColorRole.Button, QColor(246, 246, 246))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(20, 20, 20))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("red"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(130, 130, 130))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(130, 130, 130))

        self._app.setPalette(palette)
        return True
