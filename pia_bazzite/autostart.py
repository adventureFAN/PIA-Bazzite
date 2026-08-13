from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Iterable

from . import __app_id__

APP_ID = __app_id__


AUTOSTART_FILENAME = f"{APP_ID}.desktop"
AUTOSTART_ARGUMENT = "--autostart"
_AUTOSTART_MARKER = "X-PIA-Bazzite-Autostart=true"


def autostart_path() -> Path:
    """Return the user-owned XDG autostart desktop-entry path."""

    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "autostart" / AUTOSTART_FILENAME


def _desktop_exec_token(value: str) -> str:
    """Quote one Desktop Entry Exec token without involving a shell.

    Desktop Entry field codes use percent signs, so literal percent characters
    have to be doubled.  Quoting every token also makes spaces and other
    reserved characters in user/AppImage paths unambiguous.
    """

    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def _desktop_exec(command: Iterable[str]) -> str:
    return " ".join(_desktop_exec_token(part) for part in command)


def current_autostart_command() -> tuple[str, ...]:
    """Return a stable command for the current installation/development mode.

    AppImage launches must use the original AppImage path exposed through the
    APPIMAGE environment variable; PyInstaller's executable inside the
    temporary AppImage mount is not stable across logins.  Source/development
    runs use the active Python interpreter plus the absolute main.py path.
    """

    appimage = os.environ.get("APPIMAGE", "").strip()
    if appimage:
        appimage_path = Path(appimage).expanduser()
        if appimage_path.is_absolute():
            return (str(appimage_path), AUTOSTART_ARGUMENT)

    if bool(getattr(sys, "frozen", False)):
        return (str(Path(sys.executable).resolve()), AUTOSTART_ARGUMENT)

    argv0 = Path(sys.argv[0]).expanduser()
    if not argv0.is_absolute():
        argv0 = (Path.cwd() / argv0).resolve()
    else:
        argv0 = argv0.resolve()
    return (str(Path(sys.executable).resolve()), str(argv0), AUTOSTART_ARGUMENT)


def autostart_enabled(path: Path | None = None) -> bool:
    """Return whether the user XDG autostart entry currently enables the app."""

    target = path or autostart_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError:
        # A present but unreadable entry is not something the app should claim
        # as safely enabled in the Options UI.
        return False

    normalized = {
        line.strip().casefold()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if "hidden=true" in normalized:
        return False
    if "x-gnome-autostart-enabled=false" in normalized:
        return False
    return True


def render_autostart_desktop(command: Iterable[str] | None = None) -> str:
    launch_command = tuple(command or current_autostart_command())
    if not launch_command:
        raise ValueError("Autostart command must not be empty.")
    if launch_command[-1] != AUTOSTART_ARGUMENT:
        raise ValueError("Autostart command must include the internal autostart argument.")

    return "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            "Name=PIA Bazzite",
            "Comment=Start PIA Bazzite after user login",
            f"Exec={_desktop_exec(launch_command)}",
            "Icon=io.github.adventurefan.PIABazzite",
            "Terminal=false",
            "NoDisplay=true",
            "Hidden=false",
            "X-GNOME-Autostart-enabled=true",
            _AUTOSTART_MARKER,
            "",
        )
    )


def set_autostart_enabled(
    enabled: bool,
    *,
    path: Path | None = None,
    command: Iterable[str] | None = None,
) -> None:
    """Enable/disable only PIA Bazzite's user-owned XDG autostart entry."""

    target = path or autostart_path()
    if not enabled:
        target.unlink(missing_ok=True)
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_autostart_desktop(command)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "AUTOSTART_ARGUMENT",
    "AUTOSTART_FILENAME",
    "autostart_enabled",
    "autostart_path",
    "current_autostart_command",
    "render_autostart_desktop",
    "set_autostart_enabled",
]
