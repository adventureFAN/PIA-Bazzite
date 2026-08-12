from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
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

from .i18n import language, tr
from .settings import bool_value


OPTIONS_DIALOG_WIDTH = 560
OPTIONS_DIALOG_HEIGHT = 330
OPTIONS_LABEL_COLUMN_WIDTH = 230
OPTIONS_FIELD_WIDTH = 250


@dataclass(frozen=True, slots=True)
class OptionsValues:
    language_code: str
    theme: str
    quit_behavior: str
    tray_enabled: bool


class OptionsDialog(QDialog):
    """Edit ordinary persistent UI preferences in one modal dialog.

    Security-sensitive actions such as toggling the Session Kill Switch and
    commands such as re-entering credentials intentionally remain outside this
    dialog.  The dialog only edits ordinary preferences and applies nothing
    until the user presses Save.
    """

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
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
        layout.addWidget(appearance_group)
        layout.addStretch()
        layout.addWidget(buttons)

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
        )
