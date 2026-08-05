from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "de")
_RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "i18n"


def _load(language: str) -> dict[str, str]:
    path = _RESOURCE_DIR / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


STRINGS = {code: _load(code) for code in SUPPORTED_LANGUAGES}


def set_language(language: str) -> None:
    global _LANGUAGE
    _LANGUAGE = language if language in SUPPORTED_LANGUAGES else "en"


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
