#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QCoreApplication, QPoint, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from pia_bazzite.gui import COMPACT_SIZE, LOG_SIZE, MainWindow
from pia_bazzite.i18n import set_language, tr
from pia_bazzite.kill_switch_state import KillSwitchMode
from pia_bazzite.theme import ThemeController


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open the real PIA Bazzite main window with the optional stage-4C "
            "runtime states. No networking or privileged helper is used."
        )
    )
    parser.add_argument("--language", choices=("en", "de"), default="de")
    parser.add_argument(
        "--theme",
        choices=("system", "light", "dark"),
        default="system",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Exercise every optional runtime state offscreen and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    QCoreApplication.setOrganizationName("adventureFAN")
    QCoreApplication.setApplicationName("PIA Bazzite Stage 4C Preview")

    app = QApplication(sys.argv)
    app.setApplicationDisplayName("PIA Bazzite")
    app.setQuitOnLastWindowClosed(True)

    set_language(args.language)
    theme_controller = ThemeController(app)
    theme_controller.apply(args.theme)

    with tempfile.TemporaryDirectory(prefix="pia-bazzite-stage4c-") as temp_dir:
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
            expected = (
                KillSwitchMode.READY,
                KillSwitchMode.ARMED,
                KillSwitchMode.VPN_ONLY,
                KillSwitchMode.ACTIVE,
                KillSwitchMode.BLOCKING,
                KillSwitchMode.ERROR,
            )
            window.show()
            app.processEvents()
            observed = []
            for index, state in enumerate(window._stage4_preview_states):
                window._set_stage4_preview_state(index, log_transition=True)
                app.processEvents()
                observed.append(state.mode)
                if window.kill_switch_status_widget.state is not state:
                    raise RuntimeError("Main window did not apply the runtime state.")
                if not window.tray.toolTip():
                    raise RuntimeError("Tray tooltip was not updated from the runtime state.")
                tooltip = window.kill_switch_status_widget.toolTip()
                if "\n" not in tooltip:
                    raise RuntimeError("A status tooltip has no deliberate line break.")
            if tuple(observed) != expected:
                raise RuntimeError("Optional runtime states are incomplete or out of order.")
            if len(window.preview_actions) != 6:
                raise RuntimeError("Preview menu does not expose all optional states.")
            if window.kill_switch_action.isEnabled():
                raise RuntimeError("Safe preview unexpectedly enabled the real Kill Switch action.")
            if window.kill_switch_action.text() != tr("menu.kill_switch"):
                raise RuntimeError("Kill Switch option was not translated in the real menu.")
            expected_armed_menu = tr("kill_switch.state.armed").replace("&", "&&")
            if window.preview_actions[1].text() != expected_armed_menu:
                raise RuntimeError("Preview menu did not preserve the literal ampersand.")
            expected_size = window._expanded_log_size()
            if window.size() != expected_size:
                raise RuntimeError("Expanded preview window did not apply its computed size.")
            if window.width() != LOG_SIZE.width():
                raise RuntimeError("Expanded preview window has an unexpected width.")
            if window.height() < LOG_SIZE.height():
                raise RuntimeError("Expanded preview window is shorter than the legacy minimum.")
            if window.height() <= COMPACT_SIZE.height():
                raise RuntimeError("Expanded preview window did not grow beyond compact mode.")
            log_bottom = window.log_view.mapTo(
                window.log_panel,
                QPoint(0, window.log_view.height()),
            ).y()
            button_top = min(
                button.mapTo(window.log_panel, QPoint(0, 0)).y()
                for button in (
                    window.log_copy_button,
                    window.log_save_button,
                    window.log_clear_button,
                )
            )
            if button_top < log_bottom:
                raise RuntimeError("Live Log action buttons overlap the log text view.")
            QTimer.singleShot(0, app.quit)
        else:
            window.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
