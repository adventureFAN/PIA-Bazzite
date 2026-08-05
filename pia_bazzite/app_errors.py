from __future__ import annotations

from .i18n import tr


class AppError(RuntimeError):
    """An error that can be shown to a non-technical user."""

    def __init__(self, title_key: str, message_key: str, *, details: str = "") -> None:
        super().__init__(message_key)
        self.title_key = title_key
        self.message_key = message_key
        self.details = details

    @property
    def title(self) -> str:
        return tr(self.title_key)

    @property
    def message(self) -> str:
        return tr(self.message_key)


def friendly_error(error: BaseException) -> AppError:
    if isinstance(error, AppError):
        return error
    return AppError(
        "error.unexpected.title",
        "error.unexpected.message",
        details=f"{type(error).__name__}: {error}",
    )
