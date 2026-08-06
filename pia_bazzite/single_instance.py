from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def instance_is_running(name: str, *, timeout_ms: int = 250) -> bool:
    """Return True only when a live local instance accepts connections.

    A stale local-server socket does not count as a running instance because
    ``waitForConnected`` must complete successfully. The probe never removes
    sockets and never sends an activation request.
    """

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
        self._name = name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)

    def claim(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(250):
            probe.write(b"activate")
            probe.flush()
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            return False

        # A stale socket can remain after a crash.
        QLocalServer.removeServer(self._name)
        return self._server.listen(self._name)

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
