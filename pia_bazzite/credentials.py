from __future__ import annotations

from dataclasses import dataclass

import keyring
from keyring.errors import KeyringError
from PySide6.QtCore import QSettings

from .app_errors import AppError


SERVICE_NAME = "PIA Bazzite"


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str


class CredentialStore:
    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def stored_username(self) -> str:
        return str(self._settings.value("account/username", "")).strip()

    def load(self) -> Credentials | None:
        username = self.stored_username()
        if not username:
            return None
        try:
            password = keyring.get_password(SERVICE_NAME, username)
        except KeyringError as exc:
            raise AppError(
                "error.keyring_read.title",
                "error.keyring_read.message",
                details=str(exc),
            ) from exc
        if not password:
            return None
        return Credentials(username=username, password=password)

    def save(self, credentials: Credentials) -> None:
        old_username = self.stored_username()
        try:
            keyring.set_password(SERVICE_NAME, credentials.username, credentials.password)
            if old_username and old_username != credentials.username:
                try:
                    keyring.delete_password(SERVICE_NAME, old_username)
                except KeyringError:
                    pass
        except KeyringError as exc:
            raise AppError(
                "error.keyring_save.title",
                "error.keyring_save.message",
                details=str(exc),
            ) from exc
        self._settings.setValue("account/username", credentials.username)
        self._settings.sync()

    def clear(self) -> None:
        username = self.stored_username()
        if username:
            try:
                keyring.delete_password(SERVICE_NAME, username)
            except KeyringError:
                pass
        self._settings.remove("account/username")
        self._settings.sync()


def keyring_available() -> tuple[bool, str]:
    try:
        backend = keyring.get_keyring()
        priority = float(getattr(backend, "priority", 0))
    except Exception as exc:
        return False, str(exc)
    backend_name = f"{backend.__class__.__module__}.{backend.__class__.__name__}"
    if priority <= 0 or "fail" in backend_name.casefold():
        return False, backend_name
    return True, backend_name
