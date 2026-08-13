from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .settings import state_dir


def instance_is_running(name: str, *, timeout_ms: int = 250) -> bool:
    """Return True only when a live local instance accepts connections."""

    if not name.strip():
        raise ValueError("Single-instance name must not be empty.")
    if timeout_ms <= 0 or timeout_ms > 5000:
        raise ValueError("Single-instance probe timeout must be 1..5000 ms.")

    application = QCoreApplication.instance()
    if application is None:
        application = QCoreApplication([])

    probe = QLocalSocket()
    probe.connectToServer(name)
    connected = probe.waitForConnected(timeout_ms)
    if connected:
        probe.abort()
    del application
    return connected


class SingleInstance(QObject):
    activate_requested = Signal()

    def __init__(self, name: str) -> None:
        super().__init__()
        if not name.strip():
            raise ValueError("Single-instance name must not be empty.")
        self._name = name
        safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
        self._lock = QLockFile(str(state_dir() / f"{safe_name}.instance.lock"))
        # A lock is owned for the lifetime of this process.  QLockFile can
        # recover locks whose recorded process no longer exists; do not use a
        # time-only expiry that could race a slow but live first instance.
        self._lock.setStaleLockTime(0)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)

    def _activate_existing(self, *, request_activation: bool = True) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if not probe.waitForConnected(250):
            return False
        if request_activation:
            probe.write(b"activate")
            probe.flush()
            probe.waitForBytesWritten(250)
        probe.disconnectFromServer()
        return True

    def claim(self, *, activate_existing: bool = True) -> bool:
        # The lock serializes stale-socket cleanup.  Without it, two processes
        # starting together can both observe no listener and one can remove the
        # other's just-created QLocalServer socket.
        if not self._lock.tryLock(0):
            self._activate_existing(request_activation=activate_existing)
            return False

        if self._activate_existing(request_activation=activate_existing):
            self._lock.unlock()
            return False

        QLocalServer.removeServer(self._name)
        if self._server.listen(self._name):
            return True

        self._lock.unlock()
        return False

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.waitForReadyRead(100)
            socket.readAll()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activate_requested.emit()


__all__ = ["SingleInstance", "instance_is_running"]
