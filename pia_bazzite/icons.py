from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)

from .kill_switch_state import status_color_hex


# Keep the application icon permanently green.  Connection and kill-switch
# state changes are represented only by the tray/status icons.
_FIXED_COLORS = {
    "application": QColor("#2e7d32"),
}


def _palette_is_dark(palette: QPalette | None = None) -> bool:
    active_palette = palette
    if active_palette is None:
        app = QGuiApplication.instance()
        active_palette = app.palette() if app is not None else QPalette()
    color = active_palette.color(QPalette.ColorRole.Window)
    luminance = (0.2126 * color.red()) + (0.7152 * color.green()) + (0.0722 * color.blue())
    return luminance < 128


def _status_color(state: str, palette: QPalette | None = None) -> QColor:
    if state == "application":
        return _FIXED_COLORS["application"]
    return QColor(status_color_hex(state, dark_mode=_palette_is_dark(palette)))


def status_icon(
    state: str,
    size: int = 64,
    *,
    palette: QPalette | None = None,
) -> QIcon:
    """Create the flat PIA shield used by the app and system tray.

    The stage-4 state colors are:
    - neutral gray: ready / intentionally disconnected;
    - green: VPN connected and kill switch verified;
    - orange: VPN unavailable while the kill switch is blocking;
    - red: protection cannot be guaranteed.

    The legacy connected/disconnected/busy names remain accepted so the
    existing v0.5.0 GUI can migrate without a flag-day rewrite.
    """

    color = _status_color(state, palette)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

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


def status_dot_icon(
    state: str,
    size: int = 16,
    *,
    palette: QPalette | None = None,
) -> QIcon:
    """Create the small state dot used in the tray context menu."""

    color = _status_color(state, palette)
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
