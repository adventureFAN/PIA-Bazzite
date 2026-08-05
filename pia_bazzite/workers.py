from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(object)


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self._function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._function()
        except Exception as exc:  # GUI boundary: show a clean error instead of crashing.
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(result)
