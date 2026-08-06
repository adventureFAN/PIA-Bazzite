#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QCoreApplication, QSettings, QSize, QTimer, Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from pia_bazzite.gui import MainWindow
from pia_bazzite.i18n import set_language
from pia_bazzite.theme import ThemeController


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open the real PIA Bazzite main window with simulated stage-4B "
            "kill-switch states. No networking or privileged helper is used."
        )
    )
    parser.add_argument("--language", choices=("en", "de"), default="de")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Construct the preview offscreen, exercise all states, and exit.",
    )
    parser.add_argument(
        "--theme",
        choices=("system", "light", "dark"),
        default="system",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()

    QCoreApplication.setOrganizationName("adventureFAN")
    QCoreApplication.setApplicationName("PIA Bazzite Stage 4B Preview")

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("PIA Bazzite")
    app.setQuitOnLastWindowClosed(True)

    set_language(args.language)
    theme_controller = ThemeController(app)
    theme_controller.apply(args.theme)

    with tempfile.TemporaryDirectory(prefix="pia-bazzite-stage4b-") as temp_dir:
        settings = QSettings(
            str(Path(temp_dir) / "preview.ini"),
            QSettings.Format.IniFormat,
        )
        settings.setValue("ui/language", args.language)
        settings.setValue("ui/theme", args.theme)
        settings.setValue("ui/live_log", True)
        settings.setValue("ui/tray_enabled", False)
        settings.sync()

        window = MainWindow(
            app,
            settings,
            theme_controller,
            stage4_preview=True,
        )
        if args.smoke_test:
            for index, state in enumerate(window._stage4_preview_states):
                window._set_stage4_preview_state(
                    index,
                    log_transition=True,
                )
                if window.kill_switch_status_widget.state is not state:
                    raise RuntimeError("Preview widget did not accept the selected state.")
            if (
                window.log_view.lineWrapMode()
                != QPlainTextEdit.LineWrapMode.WidgetWidth
            ):
                raise RuntimeError("Live Log line wrapping is not enabled.")
            if (
                window.log_view.horizontalScrollBarPolicy()
                != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            ):
                raise RuntimeError("Live Log horizontal scrollbar is still enabled.")
            if window.ip_refresh_button.size() != QSize(28, 24):
                raise RuntimeError("Public-IP refresh control is not compact.")
            if window.size() != QSize(760, 780):
                raise RuntimeError("Expanded preview window has an unexpected size.")
            QTimer.singleShot(0, app.quit)
        else:
            window.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
