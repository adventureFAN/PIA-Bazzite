from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from pia_bazzite import __app_id__, __version__
from pia_bazzite.autostart import AUTOSTART_ARGUMENT
from pia_bazzite.gui import MainWindow
from pia_bazzite.i18n import set_language
from pia_bazzite.settings import bool_value, create_settings
from pia_bazzite.single_instance import SingleInstance
from pia_bazzite.theme import ThemeController


def main() -> int:
    if "--version" in sys.argv:
        print(f"PIA Bazzite {__version__}")
        return 0

    QCoreApplication.setOrganizationName("adventureFAN")
    QCoreApplication.setOrganizationDomain("github.com/adventureFAN")
    QCoreApplication.setApplicationName("PIA Bazzite")
    QCoreApplication.setApplicationVersion(__version__)

    autostart_launch = AUTOSTART_ARGUMENT in sys.argv[1:]
    qt_argv = [arg for arg in sys.argv if arg != AUTOSTART_ARGUMENT]

    app = QApplication(qt_argv)
    app.setApplicationDisplayName("PIA Bazzite")
    app.setQuitOnLastWindowClosed(False)
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName(__app_id__)

    settings = create_settings()
    set_language(str(settings.value("ui/language", "en")))

    instance = SingleInstance(__app_id__)
    if not instance.claim(activate_existing=not autostart_launch):
        return 0

    theme_controller = ThemeController(app)
    theme_controller.apply(str(settings.value("ui/theme", "system")))

    window = MainWindow(app, settings, theme_controller)
    instance.activate_requested.connect(window.show_window)
    # A login-autostart launch stays unobtrusive when the tray is actually
    # enabled.  If the tray setting was disabled (or MainWindow had to disable
    # it because the desktop exposes no system tray), keep the app reachable by
    # showing the main window.  Manual launches always show the window.
    if not autostart_launch or not bool_value(settings, "ui/tray_enabled", True):
        window.show()

    # The local reference remains alive while the event loop is running.
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
