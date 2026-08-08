from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "de")
_RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "i18n"
_QT_TRANSLATOR: Any | None = None


def _load(language: str) -> dict[str, str]:
    path = _RESOURCE_DIR / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


STRINGS = {code: _load(code) for code in SUPPORTED_LANGUAGES}


def _qt_translation_directories() -> list[Path]:
    directories: list[Path] = []
    try:
        from PySide6.QtCore import QLibraryInfo

        directories.append(
            Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        )
    except (ImportError, ModuleNotFoundError):
        # Core modules such as pia_api and network_manager deliberately remain
        # importable in non-GUI/self-test environments without PySide6.
        pass
    except Exception:
        pass

    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        directories.append(
            Path(bundle_root) / "PySide6" / "Qt" / "translations"
        )

    unique: list[Path] = []
    for directory in directories:
        if directory not in unique:
            unique.append(directory)
    return unique


def _apply_qt_translation(language_code: str) -> None:
    global _QT_TRANSLATOR
    try:
        from PySide6.QtCore import QCoreApplication, QTranslator
    except (ImportError, ModuleNotFoundError):
        # Translation of Qt-owned widgets is a GUI-only enhancement.  The
        # application translation helper must not make non-GUI modules depend
        # on PySide6 merely because they import tr().
        return

    app = QCoreApplication.instance()
    if app is None:
        return

    if _QT_TRANSLATOR is not None:
        app.removeTranslator(_QT_TRANSLATOR)
        _QT_TRANSLATOR = None

    if language_code != "de":
        return

    translator = QTranslator(app)
    for directory in _qt_translation_directories():
        candidate = directory / "qtbase_de.qm"
        if candidate.is_file() and translator.load(str(candidate)):
            app.installTranslator(translator)
            _QT_TRANSLATOR = translator
            return


def set_language(language: str) -> None:
    global _LANGUAGE
    _LANGUAGE = language if language in SUPPORTED_LANGUAGES else "en"
    _apply_qt_translation(_LANGUAGE)


def language() -> str:
    return _LANGUAGE


def tr(key: str, **values: Any) -> str:
    template = STRINGS.get(_LANGUAGE, STRINGS["en"]).get(key)
    if template is None:
        template = STRINGS["en"].get(key, key)
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return template


def validate_translations() -> list[str]:
    english = set(STRINGS["en"])
    german = set(STRINGS["de"])
    return sorted((english - german) | (german - english))
