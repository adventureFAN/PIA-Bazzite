from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


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
