from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .autostart import autostart_enabled
from .auto_connect import (
    AUTO_CONNECT_FASTEST,
    AUTO_CONNECT_KEY,
    AUTO_CONNECT_LAST,
    AUTO_CONNECT_OFF,
    auto_connect_region_id,
    normalize_auto_connect_target,
    region_auto_connect_target,
)
from .i18n import language, tr
from .models import Region
from .public_network import (
    DEFAULT_ONLINE_PUBLIC_NETWORK_PROVIDER,
    FREEIPAPI_PROVIDER,
    GEOJS_PROVIDER,
    IPWHOIS_PROVIDER,
    normalize_online_public_network_provider,
)
from .region_favorites import FavoriteRegion
from .region_names import compact_region_display_name
from .settings import bool_value


OPTIONS_DIALOG_WIDTH = 560
OPTIONS_DIALOG_HEIGHT = 440
OPTIONS_LABEL_COLUMN_WIDTH = 230
OPTIONS_FIELD_WIDTH = 250
AUTO_CONNECT_POPUP_VISIBLE_ITEMS = 20
AUTO_CONNECT_ACCENT_COLOR = "#f4c542"


class AutoConnectComboBox(QComboBox):
    """Auto-connect selector with a bounded, scrollable server popup."""

    def showPopup(self) -> None:
        super().showPopup()
        QTimer.singleShot(0, self._prepare_popup)

    def _prepare_popup(self) -> None:
        self._limit_popup_height()
        self.view().scrollToTop()

    def _limit_popup_height(self) -> None:
        view = self.view()
        visible = min(self.count(), AUTO_CONNECT_POPUP_VISIBLE_ITEMS)
        if visible <= 0:
            return
        fallback = max(24, view.fontMetrics().height() + 8)
        height = sum(max(view.sizeHintForRow(row), fallback) for row in range(visible))
        height += 2 * view.frameWidth() + 4
        view.setMaximumHeight(height)
        popup = view.window()
        popup.setMaximumHeight(height)
        if popup.height() > height:
            popup.resize(popup.width(), height)


@dataclass(frozen=True, slots=True)
class OptionsValues:
    language_code: str
    theme: str
    quit_behavior: str
    tray_enabled: bool
    autostart_enabled: bool
    public_network_provider: str
    auto_connect_target: str


class OptionsDialog(QDialog):
    """Edit ordinary persistent UI preferences in one modal dialog.

    Security-sensitive actions such as toggling the Session Kill Switch and
    commands such as re-entering credentials intentionally remain outside this
    dialog.  The dialog only edits ordinary preferences and applies nothing
    until the user presses Save.
    """

    def __init__(
        self,
        settings: QSettings,
        parent: QWidget | None = None,
        *,
        regions: tuple[Region, ...] | list[Region] = (),
        favorites: tuple[FavoriteRegion, ...] | list[FavoriteRegion] = (),
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("options.title"))
        self.setFixedSize(OPTIONS_DIALOG_WIDTH, OPTIONS_DIALOG_HEIGHT)

        self.language_combo = QComboBox()
        self._configure_combo(self.language_combo)
        self.language_combo.addItem(tr("menu.english"), "en")
        self.language_combo.addItem(tr("menu.german"), "de")
        self._select_data(self.language_combo, language())

        self.theme_combo = QComboBox()
        self._configure_combo(self.theme_combo)
        self.theme_combo.addItem(tr("menu.system"), "system")
        self.theme_combo.addItem(tr("menu.light"), "light")
        self.theme_combo.addItem(tr("menu.dark"), "dark")
        self._select_data(
            self.theme_combo,
            str(settings.value("ui/theme", "system")),
            fallback="system",
        )

        self.quit_behavior_combo = QComboBox()
        self._configure_combo(self.quit_behavior_combo)
        self.quit_behavior_combo.addItem(tr("menu.quit_ask"), "ask")
        self.quit_behavior_combo.addItem(tr("menu.quit_disconnect"), "disconnect")
        self.quit_behavior_combo.addItem(tr("menu.quit_leave"), "leave")
        self._select_data(
            self.quit_behavior_combo,
            str(settings.value("ui/quit_behavior", "ask")),
            fallback="ask",
        )

        self.tray_checkbox = QCheckBox(tr("options.tray_enabled"))
        self.tray_checkbox.setChecked(
            bool_value(settings, "ui/tray_enabled", True)
        )
        self.tray_checkbox.setToolTip(tr("tray.enabled_tooltip"))

        self.autostart_checkbox = QCheckBox(tr("options.autostart_enabled"))
        self.autostart_checkbox.setChecked(autostart_enabled())
        self.autostart_checkbox.setToolTip(tr("options.autostart_tooltip"))

        self.auto_connect_combo = AutoConnectComboBox()
        self._configure_combo(self.auto_connect_combo)
        self._populate_auto_connect_combo(regions, favorites)
        self.auto_connect_combo.setToolTip(tr("options.auto_connect_tooltip"))
        self._select_data(
            self.auto_connect_combo,
            normalize_auto_connect_target(
                settings.value(AUTO_CONNECT_KEY, AUTO_CONNECT_OFF)
            ),
            fallback=AUTO_CONNECT_OFF,
        )

        self.public_network_provider_combo = QComboBox()
        self._configure_combo(self.public_network_provider_combo)
        self.public_network_provider_combo.addItem(
            tr("options.provider.freeipapi"), FREEIPAPI_PROVIDER
        )
        self.public_network_provider_combo.addItem(
            tr("options.provider.geojs"), GEOJS_PROVIDER
        )
        self.public_network_provider_combo.addItem(
            tr("options.provider.ipwhois"), IPWHOIS_PROVIDER
        )
        self.public_network_provider_combo.setToolTip(
            tr("options.public_info_provider_tooltip")
        )
        self._select_data(
            self.public_network_provider_combo,
            normalize_online_public_network_provider(
                settings.value(
                    "network/public_info_provider",
                    DEFAULT_ONLINE_PUBLIC_NETWORK_PROVIDER,
                )
            ),
            fallback=DEFAULT_ONLINE_PUBLIC_NETWORK_PROVIDER,
        )

        general_group = QGroupBox(tr("options.general"))
        general_form = QFormLayout(general_group)
        general_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        general_form.addRow(
            self._form_label(tr("options.language")),
            self.language_combo,
        )
        general_form.addRow(
            self._form_label(tr("options.quit_behavior")),
            self.quit_behavior_combo,
        )
        general_form.addRow(self._form_label(""), self.tray_checkbox)
        general_form.addRow(self._form_label(""), self.autostart_checkbox)

        network_group = QGroupBox(tr("options.network"))
        network_form = QFormLayout(network_group)
        network_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        network_form.addRow(
            self._form_label(tr("options.auto_connect")),
            self.auto_connect_combo,
        )
        network_form.addRow(
            self._form_label(tr("options.public_info_provider")),
            self.public_network_provider_combo,
        )

        appearance_group = QGroupBox(tr("options.appearance"))
        appearance_form = QFormLayout(appearance_group)
        appearance_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        appearance_form.addRow(
            self._form_label(tr("options.theme")),
            self.theme_combo,
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button is not None:
            save_button.setText(tr("common.save"))
        if cancel_button is not None:
            cancel_button.setText(tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(general_group)
        layout.addWidget(network_group)
        layout.addWidget(appearance_group)
        layout.addStretch()
        layout.addWidget(buttons)

    def _populate_auto_connect_combo(
        self,
        regions: tuple[Region, ...] | list[Region],
        favorites: tuple[FavoriteRegion, ...] | list[FavoriteRegion],
    ) -> None:
        combo = self.auto_connect_combo
        combo.addItem(
            self._auto_connect_mode_icon("off"),
            tr("options.auto_connect.off"),
            AUTO_CONNECT_OFF,
        )
        combo.addItem(
            self._auto_connect_mode_icon("last"),
            tr("options.auto_connect.last"),
            AUTO_CONNECT_LAST,
        )
        combo.addItem(
            self._auto_connect_marker_icon("⚡"),
            tr("connection.fastest"),
            AUTO_CONNECT_FASTEST,
        )
        combo.insertSeparator(combo.count())

        current_by_id = {region.region_id: region for region in regions}
        favorite_ids = {favorite.region_id for favorite in favorites}
        available_favorites = [
            current_by_id[favorite.region_id]
            for favorite in favorites
            if favorite.region_id in current_by_id
        ]
        available_favorites.sort(key=self._region_ping_sort_key)

        for region in available_favorites:
            combo.addItem(
                self._auto_connect_marker_icon("★"),
                compact_region_display_name(region, language()),
                region_auto_connect_target(region.region_id),
            )

        normal_regions = [
            region for region in regions if region.region_id not in favorite_ids
        ]
        normal_regions.sort(key=self._region_ping_sort_key)
        if available_favorites and normal_regions:
            combo.insertSeparator(combo.count())

        for region in normal_regions:
            combo.addItem(
                compact_region_display_name(region, language()),
                region_auto_connect_target(region.region_id),
            )

        # Preserve a previously chosen fixed target even if it has disappeared
        # from the current PIA catalog.  It stays visible but disabled; Stage 4B
        # must never silently connect to a different country/server as fallback.
        saved_target = normalize_auto_connect_target(
            self.settings.value(AUTO_CONNECT_KEY, AUTO_CONNECT_OFF)
        )
        saved_region_id = auto_connect_region_id(saved_target)
        if saved_region_id and combo.findData(saved_target) < 0:
            favorite = next(
                (item for item in favorites if item.region_id == saved_region_id),
                None,
            )
            fallback_name = favorite.name if favorite is not None else saved_region_id
            combo.insertSeparator(combo.count())
            combo.addItem(
                tr("options.auto_connect.unavailable", region=fallback_name),
                saved_target,
            )
            self._set_combo_item_enabled(combo, combo.count() - 1, False)

    def _auto_connect_marker_icon(self, symbol: str) -> QIcon:
        """Draw the same gold favorite/fastest markers used by the main list."""

        size = self.auto_connect_combo.iconSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        color = QColor(AUTO_CONNECT_ACCENT_COLOR)

        if symbol == "⚡":
            # Keep the bolt independent of font/emoji fallback, matching the
            # main server selector's deliberately vector-drawn lightning icon.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            width = float(size.width())
            height = float(size.height())
            bolt = QPainterPath()
            bolt.moveTo(width * 0.58, height * 0.06)
            bolt.lineTo(width * 0.24, height * 0.53)
            bolt.lineTo(width * 0.47, height * 0.53)
            bolt.lineTo(width * 0.35, height * 0.94)
            bolt.lineTo(width * 0.76, height * 0.42)
            bolt.lineTo(width * 0.54, height * 0.42)
            bolt.closeSubpath()
            painter.fillPath(bolt, color)
        else:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            font = QFont(self.auto_connect_combo.font())
            font.setBold(True)
            font.setPixelSize(max(12, size.height() - 2))
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(
                pixmap.rect(),
                Qt.AlignmentFlag.AlignCenter,
                symbol,
            )

        painter.end()
        return QIcon(pixmap)

    def _auto_connect_mode_icon(self, role: str) -> QIcon:
        """Return a neutral icon for non-server Auto-Connect modes."""

        theme_names = {
            "off": ("process-stop", "dialog-cancel"),
            "last": ("view-refresh", "view-history", "edit-redo"),
        }
        for name in theme_names.get(role, ()):
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                return icon

        size = self.auto_connect_combo.iconSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = self.palette().color(QPalette.ColorRole.Text)

        if role == "off":
            side = min(size.width(), size.height()) * 0.48
            x = (size.width() - side) / 2
            y = (size.height() - side) / 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(int(x), int(y), int(side), int(side), 2, 2)
        else:
            pen = QPen(color, max(1.5, size.height() * 0.10))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            margin = max(2, int(size.height() * 0.18))
            width = max(1, size.width() - 2 * margin)
            height = max(1, size.height() - 2 * margin)
            painter.drawArc(margin, margin, width, height, 35 * 16, 285 * 16)
            painter.drawLine(
                int(size.width() * 0.70),
                int(size.height() * 0.18),
                int(size.width() * 0.88),
                int(size.height() * 0.22),
            )
            painter.drawLine(
                int(size.width() * 0.88),
                int(size.height() * 0.22),
                int(size.width() * 0.81),
                int(size.height() * 0.39),
            )

        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _region_ping_sort_key(region: Region) -> tuple[bool, float, str]:
        return (
            region.ping_ms is None,
            float("inf") if region.ping_ms is None else region.ping_ms,
            region.name.casefold(),
        )

    @staticmethod
    def _set_combo_item_enabled(combo: QComboBox, index: int, enabled: bool) -> None:
        model = combo.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(index)
            if item is not None:
                item.setEnabled(enabled)

    @staticmethod
    def _configure_combo(combo: QComboBox) -> None:
        # Keep every selector on the same visual grid, even when it lives in a
        # different group box with a shorter label such as "Theme".
        combo.setFixedWidth(OPTIONS_FIELD_WIDTH)

    @staticmethod
    def _form_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setFixedWidth(OPTIONS_LABEL_COLUMN_WIDTH)
        return label

    @staticmethod
    def _select_data(
        combo: QComboBox,
        value: str,
        fallback: str | None = None,
    ) -> None:
        index = combo.findData(value)
        if index < 0 and fallback is not None:
            index = combo.findData(fallback)
        if index >= 0:
            combo.setCurrentIndex(index)

    def values(self) -> OptionsValues:
        return OptionsValues(
            language_code=str(self.language_combo.currentData() or "en"),
            theme=str(self.theme_combo.currentData() or "system"),
            quit_behavior=str(self.quit_behavior_combo.currentData() or "ask"),
            tray_enabled=self.tray_checkbox.isChecked(),
            autostart_enabled=self.autostart_checkbox.isChecked(),
            public_network_provider=normalize_online_public_network_provider(
                self.public_network_provider_combo.currentData()
            ),
            auto_connect_target=normalize_auto_connect_target(
                self.auto_connect_combo.currentData()
            ),
        )
