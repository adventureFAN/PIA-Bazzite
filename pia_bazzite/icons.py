from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def status_icon(state: str, size: int = 64) -> QIcon:
    """Create the flat PIA shield used by the app and system tray."""
    colors = {
        "connected": QColor("#2e7d32"),
        "disconnected": QColor("#c62828"),
        "busy": QColor("#ef6c00"),
        "application": QColor("#2e7d32"),
    }
    color = colors.get(state, colors["application"])

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Rounded shield silhouette.
    margin = size * 0.10
    path = QPainterPath()
    path.moveTo(size / 2, margin)
    path.cubicTo(size * 0.72, margin, size * 0.84, size * 0.18, size * 0.88, size * 0.25)
    path.lineTo(size * 0.84, size * 0.57)
    path.cubicTo(size * 0.80, size * 0.78, size * 0.64, size * 0.89, size / 2, size * 0.95)
    path.cubicTo(size * 0.36, size * 0.89, size * 0.20, size * 0.78, size * 0.16, size * 0.57)
    path.lineTo(size * 0.12, size * 0.25)
    path.cubicTo(size * 0.16, size * 0.18, size * 0.28, margin, size / 2, margin)
    path.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)

    painter.setPen(QPen(QColor("white"), max(2, int(size * 0.045))))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(int(size * 0.25))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "PIA")
    painter.end()

    return QIcon(pixmap)


def status_dot_icon(state: str, size: int = 16) -> QIcon:
    """Create a small native-looking red/green status dot for menus."""
    color = QColor("#2e7d32" if state == "connected" else "#c62828")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    margin = max(2, size // 5)
    painter.setBrush(color)
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pixmap)


def system_status_icon(state: str, size: int = 18) -> QIcon:
    """Draw a plain green check or red X without a colored button background."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    if state == "ok":
        pen = QPen(QColor("#2e9b43"), max(2.0, size * 0.16))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(
            int(size * 0.18),
            int(size * 0.53),
            int(size * 0.42),
            int(size * 0.76),
        )
        painter.drawLine(
            int(size * 0.42),
            int(size * 0.76),
            int(size * 0.84),
            int(size * 0.24),
        )
    elif state == "error":
        pen = QPen(QColor("#d32f2f"), max(2.0, size * 0.15))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            int(size * 0.22),
            int(size * 0.22),
            int(size * 0.78),
            int(size * 0.78),
        )
        painter.drawLine(
            int(size * 0.78),
            int(size * 0.22),
            int(size * 0.22),
            int(size * 0.78),
        )

    painter.end()
    return QIcon(pixmap)
