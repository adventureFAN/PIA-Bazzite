from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .icons import status_icon
from .kill_switch_state import KillSwitchViewState, status_color_hex


def _palette_is_dark(widget: QWidget) -> bool:
    color = widget.palette().color(QPalette.ColorRole.Window)
    luminance = (
        (0.2126 * color.red())
        + (0.7152 * color.green())
        + (0.0722 * color.blue())
    )
    return luminance < 128


class KillSwitchStatusWidget(QFrame):
    """Compact, user-facing presentation of one verified kill-switch state.

    The visible copy is intentionally short. The full explanation is exposed
    as a tooltip on the complete widget and its child labels. This keeps the
    main window readable without hiding the security consequence.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: KillSwitchViewState | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("killSwitchStatusPanel")
        self.setMinimumHeight(92)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(QSize(58, 58))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel()
        self.title_label.setObjectName("killSwitchStatusTitle")
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(20)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        self.summary_label = QLabel()
        self.summary_label.setObjectName("killSwitchStatusSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 14, 0, 0)
        text_layout.setSpacing(1)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.summary_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(self.icon_label)
        layout.addLayout(text_layout, 1)

    @property
    def state(self) -> KillSwitchViewState | None:
        return self._state

    def set_state(self, state: KillSwitchViewState) -> None:
        self._state = state
        self.refresh()

    def refresh(self) -> None:
        if self._state is None:
            return

        dark_mode = _palette_is_dark(self)
        color = status_color_hex(
            self._state.icon_state,
            dark_mode=dark_mode,
        )
        self.icon_label.setPixmap(
            status_icon(
                self._state.icon_state,
                52,
                palette=self.palette(),
            ).pixmap(52, 52)
        )
        self.title_label.setText(tr(self._state.title_key))
        title_palette = QPalette(self.title_label.palette())
        title_palette.setColor(
            QPalette.ColorRole.WindowText,
            QColor(color),
        )
        self.title_label.setPalette(title_palette)
        self.summary_label.setText(tr(self._state.summary_key))

        tooltip = tr(self._state.detail_key)
        self.setToolTip(tooltip)
        self.icon_label.setToolTip(tooltip)
        self.title_label.setToolTip(tooltip)
        self.summary_label.setToolTip(tooltip)


__all__ = ["KillSwitchStatusWidget"]
