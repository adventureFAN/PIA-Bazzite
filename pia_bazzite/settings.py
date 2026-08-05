from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings


APP_ID = "io.github.adventurefan.PIABazzite"
APP_SLUG = "pia-bazzite"


def _xdg_path(environment_name: str, fallback: Path) -> Path:
    value = os.environ.get(environment_name, "").strip()
    return Path(value).expanduser() if value else fallback


def config_dir() -> Path:
    path = _xdg_path("XDG_CONFIG_HOME", Path.home() / ".config") / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = _xdg_path("XDG_CACHE_HOME", Path.home() / ".cache") / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    path = _xdg_path("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_settings() -> QSettings:
    settings = QSettings(str(config_dir() / "settings.ini"), QSettings.Format.IniFormat)
    if not settings.value("migration/v04_complete", False, type=bool):
        old = QSettings("AlexTools", "PIA Bazzite")
        for key in old.allKeys():
            if not settings.contains(key):
                settings.setValue(key, old.value(key))
        settings.setValue("migration/v04_complete", True)
        settings.sync()
    return settings


def bool_value(settings: QSettings, key: str, default: bool) -> bool:
    return settings.value(key, default, type=bool)
