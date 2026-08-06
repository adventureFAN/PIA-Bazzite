from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QSize, QThreadPool, QTimer, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QFont,
    QFontDatabase,
    QKeySequence,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import __app_id__, __version__, network_manager
from .app_errors import AppError, friendly_error
from .credentials import CredentialStore, Credentials
from .i18n import language, set_language, tr
from .icons import status_dot_icon, status_icon, system_status_icon
from .logging_utils import mask_ip_address, redact_secrets
from .kill_switch_state import (
    KillSwitchViewState,
    sample_kill_switch_states,
)
from .kill_switch_runtime import KillSwitchRuntimeController
from .kill_switch_widgets import KillSwitchStatusWidget
from .models import PublicNetworkInfo, Region, SystemCheck
from .pia_api import (
    create_wireguard_config,
    fetch_public_network_info,
    fetch_regions,
    measure_latencies,
)
from .region_cache import load_regions, save_regions
from .region_names import (
    localized_region_name,
    public_country_name,
    region_display_name,
    search_haystack,
)
from .settings import bool_value, cache_dir, state_dir
from .system_checks import required_checks_pass, run_system_checks
from .theme import ThemeController
from .workers import FunctionWorker


FASTEST_ID = "__fastest__"
COMPACT_SIZE = QSize(760, 510)
LOG_SIZE = QSize(800, 780)


class CredentialsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        username: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("credentials.title"))
        self.setMinimumWidth(450)

        self.username_edit = QLineEdit(username)
        self.username_edit.setPlaceholderText(tr("credentials.username_placeholder"))

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(tr("credentials.password_placeholder"))

        form = QFormLayout()
        form.addRow(tr("credentials.username"), self.username_edit)
        form.addRow(tr("credentials.password"), self.password_edit)

        explanation = QLabel(tr("credentials.explanation"))
        explanation.setWordWrap(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button is not None:
            save_button.setText(tr("credentials.save"))
        if cancel_button is not None:
            cancel_button.setText(tr("common.cancel"))
        self.buttons.accepted.connect(self._validate)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(explanation)
        layout.addWidget(self.buttons)

    def _validate(self) -> None:
        if not self.username_edit.text().strip() or not self.password_edit.text():
            QMessageBox.warning(
                self,
                tr("credentials.missing_title"),
                tr("credentials.missing_message"),
            )
            return
        self.accept()

    def credentials(self) -> Credentials:
        return Credentials(
            username=self.username_edit.text().strip(),
            password=self.password_edit.text(),
        )


class SystemCheckDialog(QDialog):
    def __init__(
        self,
        checks: list[SystemCheck],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("system.title"))
        self.setMinimumWidth(590)

        layout = QVBoxLayout(self)

        intro = QLabel(tr("system.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for check in checks:
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            row = QHBoxLayout(frame)

            symbol = QLabel("✓" if check.ok else "✕")
            symbol.setMinimumWidth(26)
            symbol.setStyleSheet(
                "font-size: 20px; font-weight: 700; "
                + ("color: #2e7d32;" if check.ok else "color: #c62828;")
            )

            label = tr(f"check.{check.key}.label")
            explanation = tr(
                f"check.{check.key}.explanation",
                detail=escape(check.detail),
            )
            requirement = ""
            if not check.ok:
                requirement = (
                    tr("system.required_problem")
                    if check.required
                    else tr("system.optional_problem")
                )
                requirement = f"<br><i>{escape(requirement)}</i>"

            text = QLabel(
                f"<b>{escape(label)}</b><br>{explanation}{requirement}"
            )
            text.setWordWrap(True)

            row.addWidget(symbol, alignment=Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            layout.addWidget(frame)

        note = QLabel(tr("system.keyring_note"))
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(tr("common.close"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class QuitDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice = ""
        self.setWindowTitle(tr("quit.title"))
        self.setMinimumWidth(480)

        question = QLabel(tr("quit.question"))
        question.setWordWrap(True)

        self.remember_checkbox = QCheckBox(tr("quit.remember"))

        disconnect_button = QPushButton(tr("quit.disconnect"))
        leave_button = QPushButton(tr("quit.leave"))
        cancel_button = QPushButton(tr("quit.cancel"))

        disconnect_button.clicked.connect(
            lambda: self._finish("disconnect")
        )
        leave_button.clicked.connect(lambda: self._finish("leave"))
        cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(question)
        layout.addWidget(self.remember_checkbox)
        layout.addSpacing(8)
        layout.addWidget(disconnect_button)
        layout.addWidget(leave_button)
        layout.addWidget(cancel_button)

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class MainWindow(QMainWindow):
    def __init__(
        self,
        app: QApplication,
        settings: QSettings,
        theme_controller: ThemeController,
        *,
        stage4_preview: bool = False,
        kill_switch_status_reader: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.settings = settings
        self.theme_controller = theme_controller
        self.credential_store = CredentialStore(settings)
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: set[FunctionWorker] = set()
        self._stage4_preview = bool(stage4_preview)
        self._stage4_preview_states = sample_kill_switch_states()
        self._stage4_preview_index = 0
        self._kill_switch_view_state: KillSwitchViewState = (
            self._stage4_preview_states[0]
        )
        self._last_kill_switch_mode: str | None = None
        self.kill_switch_runtime = KillSwitchRuntimeController(
            settings,
            status_reader=kill_switch_status_reader,
        )

        self.session_credentials: Credentials | None = None
        self.regions: list[Region] = load_regions()
        self.system_checks: list[SystemCheck] = []
        self.public_info: PublicNetworkInfo | None = None

        self._connection_busy = False
        self._regions_busy = False
        self._public_info_busy = False
        self._last_connected_state: bool | None = None
        self._active_region_id = str(
            settings.value("connection/active_region_id", "")
        ).strip()
        self._active_region_fallback = str(
            settings.value("connection/active_region_name", "")
        ).strip()
        self._allow_close = False
        self._close_hint_shown = False
        self._initial_setup_done = False

        # An empty per-window title lets KDE/Qt show only applicationDisplayName.
        self.setWindowTitle("")
        self.setWindowIcon(status_icon("application"))
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )

        self._create_actions()
        self._create_menu_bar()
        self._create_main_ui()
        self._create_live_log()
        self._create_tray()
        self._activate_kill_switch_status_ui()
        if self._stage4_preview:
            self._create_stage4_preview_menu()

        self.retranslate()
        self._apply_live_log_setting(initial=True)

        if self._stage4_preview:
            self.status_timer = QTimer(self)
            self.tray.hide()
            self.tray_action.setEnabled(False)
            self._prepare_stage4_preview()
            self.log("info", "log.started", version=__version__)
            self._set_stage4_preview_state(0, log_transition=False)
            self.log(
                self._kill_switch_view_state.log_level,
                self._kill_switch_view_state.log_key,
            )
            return

        self._apply_tray_setting(log_change=False)
        self.run_system_check(show_dialog=False, log_result=True)
        self._populate_region_combo()
        self.update_connection_status(force=True)

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(3000)
        self.status_timer.timeout.connect(self.update_connection_status)
        self.status_timer.start()

        self.log("info", "log.started", version=__version__)

        QTimer.singleShot(0, self._first_start)
        QTimer.singleShot(150, self.refresh_regions)
        QTimer.singleShot(500, lambda: self.refresh_public_info(show_errors=False))

    @staticmethod
    def _set_demi_bold(label: QLabel) -> None:
        font = QFont(label.font())
        font.setWeight(QFont.Weight.DemiBold)
        label.setFont(font)

    # ------------------------------------------------------------------
    # UI creation
    # ------------------------------------------------------------------
    def _create_actions(self) -> None:
        self.exit_action = QAction(self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.request_quit)

        self.toggle_vpn_action = QAction(self)
        self.toggle_vpn_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.toggle_vpn_action.triggered.connect(self.toggle_connection)
        self.addAction(self.toggle_vpn_action)

        self.reload_action = QAction(self)
        self.reload_action.setShortcut(QKeySequence("Ctrl+R"))
        self.reload_action.triggered.connect(self.refresh_regions)
        self.addAction(self.reload_action)

        self.ping_action = QAction(self)
        self.ping_action.setShortcut(QKeySequence("Ctrl+P"))
        self.ping_action.triggered.connect(self.refresh_pings)
        self.addAction(self.ping_action)

        self.ip_action = QAction(self)
        self.ip_action.setShortcut(QKeySequence("Ctrl+I"))
        self.ip_action.triggered.connect(
            lambda: self.refresh_public_info(show_errors=True)
        )
        self.addAction(self.ip_action)

        self.system_action = QAction(self)
        self.system_action.setShortcut(QKeySequence("F5"))
        self.system_action.triggered.connect(
            lambda: self.run_system_check(show_dialog=True, log_result=True)
        )
        self.addAction(self.system_action)

        self.credentials_action = QAction(self)
        self.credentials_action.triggered.connect(
            lambda: self.edit_credentials(first_run=False)
        )

        self.live_log_action = QAction(self)
        self.live_log_action.setCheckable(True)
        self.live_log_action.setShortcut(QKeySequence("Ctrl+L"))
        self.live_log_action.toggled.connect(self._set_live_log_visible)

        self.tray_action = QAction(self)
        self.tray_action.setCheckable(True)
        self.tray_action.toggled.connect(self._tray_setting_changed)

        self.about_action = QAction(self)
        self.about_action.setShortcut(QKeySequence("F1"))
        self.about_action.triggered.connect(self.show_about)

        self.english_action = QAction(self)
        self.english_action.setCheckable(True)
        self.english_action.triggered.connect(lambda: self.change_language("en"))

        self.german_action = QAction(self)
        self.german_action.setCheckable(True)
        self.german_action.triggered.connect(lambda: self.change_language("de"))

        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_group.addAction(self.english_action)
        self.language_group.addAction(self.german_action)

        self.system_theme_action = QAction(self)
        self.system_theme_action.setCheckable(True)
        self.system_theme_action.triggered.connect(
            lambda: self.change_theme("system")
        )
        self.light_theme_action = QAction(self)
        self.light_theme_action.setCheckable(True)
        self.light_theme_action.triggered.connect(
            lambda: self.change_theme("light")
        )
        self.dark_theme_action = QAction(self)
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.triggered.connect(
            lambda: self.change_theme("dark")
        )

        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        for action in (
            self.system_theme_action,
            self.light_theme_action,
            self.dark_theme_action,
        ):
            self.theme_group.addAction(action)

        self.quit_ask_action = QAction(self)
        self.quit_ask_action.setCheckable(True)
        self.quit_ask_action.triggered.connect(
            lambda: self.change_quit_behavior("ask")
        )
        self.quit_disconnect_action = QAction(self)
        self.quit_disconnect_action.setCheckable(True)
        self.quit_disconnect_action.triggered.connect(
            lambda: self.change_quit_behavior("disconnect")
        )
        self.quit_leave_action = QAction(self)
        self.quit_leave_action.setCheckable(True)
        self.quit_leave_action.triggered.connect(
            lambda: self.change_quit_behavior("leave")
        )

        self.quit_group = QActionGroup(self)
        self.quit_group.setExclusive(True)
        for action in (
            self.quit_ask_action,
            self.quit_disconnect_action,
            self.quit_leave_action,
        ):
            self.quit_group.addAction(action)

    def _create_menu_bar(self) -> None:
        self.file_menu = self.menuBar().addMenu("")
        self.file_menu.addAction(self.exit_action)

        self.options_menu = self.menuBar().addMenu("")

        self.language_menu = self.options_menu.addMenu("")
        self.language_menu.addAction(self.english_action)
        self.language_menu.addAction(self.german_action)

        self.appearance_menu = self.options_menu.addMenu("")
        self.appearance_menu.addAction(self.system_theme_action)
        self.appearance_menu.addAction(self.light_theme_action)
        self.appearance_menu.addAction(self.dark_theme_action)

        self.quit_behavior_menu = self.options_menu.addMenu("")
        self.quit_behavior_menu.addAction(self.quit_ask_action)
        self.quit_behavior_menu.addAction(self.quit_disconnect_action)
        self.quit_behavior_menu.addAction(self.quit_leave_action)

        self.options_menu.addSeparator()
        self.options_menu.addAction(self.credentials_action)
        self.options_menu.addAction(self.live_log_action)
        self.options_menu.addAction(self.tray_action)

        self.help_menu = self.menuBar().addMenu("")
        self.help_menu.addAction(self.about_action)

    def _create_main_ui(self) -> None:
        central = QWidget()
        page = QVBoxLayout(central)
        page.setContentsMargins(22, 18, 22, 18)
        page.setSpacing(12)

        self.status_group = QGroupBox()
        status_layout = QVBoxLayout(self.status_group)

        self.kill_switch_status_widget = KillSwitchStatusWidget()
        self.kill_switch_status_widget.hide()
        status_layout.addWidget(self.kill_switch_status_widget)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 20px; font-weight: 650;")
        self.status_detail_label = QLabel()
        self.status_detail_label.setWordWrap(True)

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.status_detail_label)

        facts = QGridLayout()
        facts.setHorizontalSpacing(20)
        facts.setVerticalSpacing(7)

        self.ip_caption = QLabel()
        self._set_demi_bold(self.ip_caption)
        self.ip_value = QLabel()
        self.ip_refresh_button = QToolButton()
        self.ip_refresh_button.setText("↻")
        self.ip_refresh_button.setFixedSize(28, 24)
        self.ip_refresh_button.clicked.connect(
            lambda: self.refresh_public_info(show_errors=True)
        )
        ip_widget = QWidget()
        ip_layout = QHBoxLayout(ip_widget)
        ip_layout.setContentsMargins(0, 0, 0, 0)
        ip_layout.setSpacing(7)
        ip_layout.addWidget(self.ip_value)
        ip_layout.addWidget(self.ip_refresh_button)
        ip_layout.addStretch()
        facts.addWidget(self.ip_caption, 0, 0)
        facts.addWidget(ip_widget, 0, 1)

        self.country_caption = QLabel()
        self._set_demi_bold(self.country_caption)
        self.country_value = QLabel()
        facts.addWidget(self.country_caption, 1, 0)
        facts.addWidget(self.country_value, 1, 1)

        self.ipv6_caption = QLabel()
        self._set_demi_bold(self.ipv6_caption)
        self.ipv6_value = QLabel()
        facts.addWidget(self.ipv6_caption, 2, 0)
        facts.addWidget(self.ipv6_value, 2, 1)

        self.dns_caption = QLabel()
        self._set_demi_bold(self.dns_caption)
        self.dns_value = QLabel()
        facts.addWidget(self.dns_caption, 3, 0)
        facts.addWidget(self.dns_value, 3, 1)

        self.kill_switch_caption = QLabel()
        self._set_demi_bold(self.kill_switch_caption)
        self.kill_switch_value = QLabel()
        facts.addWidget(self.kill_switch_caption, 4, 0)
        facts.addWidget(self.kill_switch_value, 4, 1)

        facts.setColumnStretch(1, 1)
        status_layout.addLayout(facts)
        page.addWidget(self.status_group)

        self.connection_group = QGroupBox()
        connection_layout = QVBoxLayout(self.connection_group)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._populate_region_combo)
        connection_layout.addWidget(self.search_edit)

        self.region_combo = QComboBox()
        self.region_combo.setMinimumHeight(38)
        self.region_combo.currentIndexChanged.connect(self._selection_changed)
        connection_layout.addWidget(self.region_combo)

        self.connection_button = QPushButton()
        self.connection_button.setMinimumHeight(46)
        self.connection_button.clicked.connect(self.toggle_connection)

        tools = QHBoxLayout()
        tools.setSpacing(8)

        self.reload_button = QPushButton()
        self.reload_button.clicked.connect(self.refresh_regions)

        self.system_button = QPushButton()
        self.system_button.clicked.connect(
            lambda: self.run_system_check(show_dialog=True, log_result=True)
        )

        self.ping_button = QPushButton()
        self.ping_button.clicked.connect(self.refresh_pings)

        tools.addWidget(self.reload_button)
        tools.addWidget(self.system_button)
        tools.addWidget(self.ping_button)
        connection_layout.addLayout(tools)
        connection_layout.addWidget(self.connection_button)

        page.addWidget(self.connection_group)
        self.main_layout = page

        self.setCentralWidget(central)

    def _create_live_log(self) -> None:
        self.log_panel = QFrame()
        self.log_panel.setFrameShape(QFrame.Shape.StyledPanel)
        self.log_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.log_title_label = QLabel()
        self._set_demi_bold(self.log_title_label)

        self.log_close_button = QPushButton("×")
        self.log_close_button.setFlat(True)
        self.log_close_button.setFixedSize(28, 26)
        self.log_close_button.clicked.connect(
            lambda: self.live_log_action.setChecked(False)
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.log_title_label)
        header.addStretch()
        header.addWidget(self.log_close_button)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_view.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.log_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.log_view.document().setMaximumBlockCount(1500)
        self.log_view.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self.log_view.setMinimumHeight(215)

        self.log_copy_button = QPushButton()
        self.log_copy_button.clicked.connect(self.copy_log)

        self.log_save_button = QPushButton()
        self.log_save_button.clicked.connect(self.save_log)

        self.log_clear_button = QPushButton()
        self.log_clear_button.clicked.connect(self.log_view.clear)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.addStretch()
        buttons.addWidget(self.log_copy_button)
        buttons.addWidget(self.log_save_button)
        buttons.addWidget(self.log_clear_button)

        panel_layout = QVBoxLayout(self.log_panel)
        panel_layout.setContentsMargins(10, 8, 10, 10)
        panel_layout.setSpacing(6)
        panel_layout.addLayout(header)
        panel_layout.addWidget(self.log_view, 1)
        panel_layout.addLayout(buttons)

        self.main_layout.addWidget(self.log_panel, 1)
        self.log_panel.hide()

    def _create_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(status_icon("disconnected"))
        self.tray.activated.connect(self._tray_activated)
        self._rebuild_tray_menu()

    def _activate_kill_switch_status_ui(self) -> None:
        """Use the compact state widget as the single status presentation."""

        self.status_label.hide()
        self.status_detail_label.hide()
        self.kill_switch_caption.hide()
        self.kill_switch_value.hide()
        self.kill_switch_status_widget.show()

    def _create_stage4_preview_menu(self) -> None:
        self.preview_menu = self.menuBar().addMenu("")
        self.preview_group = QActionGroup(self)
        self.preview_group.setExclusive(True)
        self.preview_actions: list[QAction] = []

        for index, state in enumerate(self._stage4_preview_states):
            action = QAction(self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(
                lambda checked=False, selected=index: (
                    self._set_stage4_preview_state(
                        selected,
                        log_transition=True,
                    )
                )
            )
            self.preview_group.addAction(action)
            self.preview_menu.addAction(action)
            self.preview_actions.append(action)

    def _prepare_stage4_preview(self) -> None:
        self.regions = []
        self.region_combo.blockSignals(True)
        self.region_combo.clear()
        self.region_combo.addItem("Netherlands — Amsterdam", "preview")
        self.region_combo.setCurrentIndex(0)
        self.region_combo.blockSignals(False)
        self.search_edit.setText("")
        self.search_edit.setEnabled(False)
        self.region_combo.setEnabled(False)
        self.reload_button.setEnabled(False)
        self.ping_button.setEnabled(False)
        self.ip_refresh_button.setEnabled(False)
        self.system_button.setText(tr("preview.stage4b.notice"))
        self.system_button.setIcon(system_status_icon("ok"))
        self.system_button.setEnabled(False)

        for action in (
            self.toggle_vpn_action,
            self.reload_action,
            self.ping_action,
            self.ip_action,
            self.system_action,
            self.credentials_action,
        ):
            action.setEnabled(False)

        self._rebuild_tray_menu()

    def _apply_kill_switch_view_state(
        self,
        state: KillSwitchViewState,
        *,
        log_transition: bool,
    ) -> None:
        previous_mode = self._last_kill_switch_mode
        self._kill_switch_view_state = state
        self._last_kill_switch_mode = state.mode.value
        self.kill_switch_status_widget.set_state(state)
        self.tray.setIcon(status_icon(state.icon_state))
        self.tray.setToolTip(tr(state.tray_tooltip_key))

        if (
            log_transition
            and previous_mode is not None
            and previous_mode != state.mode.value
        ):
            self.log(state.log_level, state.log_key)

    def _set_stage4_preview_state(
        self,
        index: int,
        *,
        log_transition: bool,
    ) -> None:
        if not self._stage4_preview:
            return
        if index < 0 or index >= len(self._stage4_preview_states):
            return

        self._stage4_preview_index = index
        state = self._stage4_preview_states[index]
        previous_mode = self._kill_switch_view_state.mode
        self._apply_kill_switch_view_state(
            state,
            log_transition=False,
        )

        if hasattr(self, "preview_actions"):
            for action_index, action in enumerate(self.preview_actions):
                action.blockSignals(True)
                action.setChecked(action_index == index)
                action.blockSignals(False)

        if state.mode.value in {"ready", "armed"}:
            self.ip_value.setText("198.51.100.24")
            self.country_value.setText("Germany" if language() == "en" else "Deutschland")
            self.ipv6_value.setText(tr("status.ipv6_normal"))
            self.dns_value.setText(tr("status.dns_system"))
            self.connection_button.setText(tr("connection.connect"))
        elif state.mode.value in {"vpn_only", "active"}:
            self.ip_value.setText("203.0.113.42")
            self.country_value.setText("Netherlands" if language() == "en" else "Niederlande")
            self.ipv6_value.setText(tr("status.ipv6_blocked"))
            self.dns_value.setText(tr("status.dns_pia"))
            self.connection_button.setText(tr("connection.disconnect"))
        elif state.mode.value == "blocking":
            self.ip_value.setText("—")
            self.country_value.setText("—")
            self.ipv6_value.setText(tr("status.ipv6_blocked"))
            self.dns_value.setText("—")
            self.connection_button.setText(tr("connection.connect"))
        else:
            self.ip_value.setText(tr("common.unknown"))
            self.country_value.setText(tr("common.unknown"))
            self.ipv6_value.setText(tr("common.unknown"))
            self.dns_value.setText(tr("common.unknown"))
            self.connection_button.setText(tr("connection.connect"))

        self.connection_button.setEnabled(False)
        self._rebuild_tray_menu()

        if log_transition and previous_mode != state.mode:
            self.log(state.log_level, state.log_key)
        elif log_transition and not self.log_view.toPlainText():
            self.log(state.log_level, state.log_key)

    # ------------------------------------------------------------------
    # Translation and preferences
    # ------------------------------------------------------------------
    def retranslate(self) -> None:
        self.file_menu.setTitle(tr("menu.file"))
        self.exit_action.setText(tr("menu.exit"))

        self.options_menu.setTitle(tr("menu.options"))
        self.language_menu.setTitle(tr("menu.language"))
        self.english_action.setText(tr("menu.english"))
        self.german_action.setText(tr("menu.german"))

        self.appearance_menu.setTitle(tr("menu.appearance"))
        self.system_theme_action.setText(tr("menu.system"))
        self.light_theme_action.setText(tr("menu.light"))
        self.dark_theme_action.setText(tr("menu.dark"))

        self.quit_behavior_menu.setTitle(tr("menu.quit_behavior"))
        self.quit_ask_action.setText(tr("menu.quit_ask"))
        self.quit_disconnect_action.setText(tr("menu.quit_disconnect"))
        self.quit_leave_action.setText(tr("menu.quit_leave"))

        self.credentials_action.setText(tr("menu.credentials"))
        self.live_log_action.setText(tr("menu.live_log"))
        self.tray_action.setText(tr("menu.tray"))

        self.help_menu.setTitle(tr("menu.help"))
        self.about_action.setText(tr("menu.about"))

        self.status_group.setTitle(tr("status.group"))
        self.connection_group.setTitle(tr("connection.group"))

        self.ip_caption.setText(tr("status.public_ip"))
        self.country_caption.setText(tr("status.country"))
        self.ipv6_caption.setText(tr("status.ipv6"))
        self.dns_caption.setText(tr("status.dns"))
        self.kill_switch_caption.setText(tr("status.kill_switch"))

        self.search_edit.setPlaceholderText(tr("connection.search_placeholder"))
        self.search_edit.setToolTip(tr("connection.search_tooltip"))
        self.region_combo.setToolTip(tr("connection.combo_tooltip"))

        self.reload_button.setText(tr("connection.reload"))
        self.ping_button.setText(tr("connection.refresh_pings"))

        self.ip_refresh_button.setToolTip(tr("tooltip.public_ip_refresh"))
        self.ip_value.setToolTip(tr("tooltip.public_ip"))
        self.ipv6_value.setToolTip(tr("tooltip.ipv6"))
        self.dns_value.setToolTip(tr("tooltip.dns"))
        self.kill_switch_value.setToolTip(tr("tooltip.kill_switch"))
        self.tray_action.setToolTip(tr("tray.enabled_tooltip"))

        self.log_title_label.setText(tr("log.title"))
        self.log_close_button.setToolTip(tr("common.close"))
        self.log_copy_button.setText(tr("log.copy"))
        self.log_save_button.setText(tr("log.save"))
        self.log_clear_button.setText(tr("log.clear"))

        self.english_action.setChecked(language() == "en")
        self.german_action.setChecked(language() == "de")

        theme = str(self.settings.value("ui/theme", "system"))
        self.system_theme_action.setChecked(theme == "system")
        self.light_theme_action.setChecked(theme == "light")
        self.dark_theme_action.setChecked(theme == "dark")

        quit_behavior = str(self.settings.value("ui/quit_behavior", "ask"))
        self.quit_ask_action.setChecked(quit_behavior == "ask")
        self.quit_disconnect_action.setChecked(quit_behavior == "disconnect")
        self.quit_leave_action.setChecked(quit_behavior == "leave")

        if self._stage4_preview:
            self.system_button.setText(tr("preview.stage4b.notice"))
            self.preview_menu.setTitle(tr("preview.stage4b.menu"))
            for action, state in zip(
                self.preview_actions,
                self._stage4_preview_states,
                strict=True,
            ):
                action.setText(tr(state.title_key))
            self._set_stage4_preview_state(
                self._stage4_preview_index,
                log_transition=False,
            )
        else:
            self._populate_region_combo()
            self._update_system_button()
            self.update_connection_status(force=True)
            self._rebuild_tray_menu()

    def change_language(self, language_code: str) -> None:
        if language_code == language():
            return
        set_language(language_code)
        self.settings.setValue("ui/language", language_code)
        self.settings.sync()
        self.retranslate()
        self.log("info", "log.language_changed")

    def change_theme(self, mode: str) -> None:
        if mode not in {"system", "light", "dark"}:
            return
        self.theme_controller.apply(mode)
        self.settings.setValue("ui/theme", mode)
        self.settings.sync()
        self.retranslate()
        self.log("info", "log.theme_changed", mode=tr(f"theme.{mode}"))

    def change_quit_behavior(self, behavior: str) -> None:
        if behavior not in {"ask", "disconnect", "leave"}:
            return
        self.settings.setValue("ui/quit_behavior", behavior)
        self.settings.sync()
        self.retranslate()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def log(self, level: str, key: str, **values: Any) -> None:
        message = redact_secrets(tr(key, **values))
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_key = f"log.level.{level}"
        level_text = tr(level_key)
        self.log_view.appendPlainText(
            f"{timestamp}  {level_text:<7}  {message}"
        )

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def save_log(self) -> None:
        default_path = state_dir() / "pia-bazzite.log"
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("log.save_title"),
            str(default_path),
            "Text files (*.txt *.log);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                self.log_view.toPlainText() + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            self._show_error(
                AppError(
                    "error.unexpected.title",
                    "log.save_failed",
                    details=str(exc),
                )
            )
            return
        self.log("ok", "log.saved", path=path)

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    def _first_start(self) -> None:
        if self._initial_setup_done:
            return
        self._initial_setup_done = True

        try:
            credentials = self.credential_store.load()
        except AppError as exc:
            self._show_error(exc)
            credentials = None

        if credentials is None:
            accepted = self.edit_credentials(first_run=True)
            if not accepted:
                QMessageBox.information(
                    self,
                    tr("credentials.cancel_first_run_title"),
                    tr("credentials.cancel_first_run"),
                )

    def edit_credentials(self, *, first_run: bool) -> bool:
        username = self.credential_store.stored_username()
        dialog = CredentialsDialog(self, username=username)
        self.log("info", "log.credentials_opened")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        credentials = dialog.credentials()
        self.session_credentials = credentials
        try:
            self.credential_store.save(credentials)
        except AppError as exc:
            self._show_error(exc)
            self.log("warning", "credentials.session_log")
        else:
            self.log("ok", "credentials.saved_log")
        return True

    def _get_credentials(self) -> Credentials | None:
        if self.session_credentials is not None:
            return self.session_credentials

        try:
            stored = self.credential_store.load()
        except AppError as exc:
            self._show_error(exc)
            stored = None

        if stored is not None:
            return stored

        if self.edit_credentials(first_run=False):
            return self.session_credentials or self.credential_store.load()
        return None

    # ------------------------------------------------------------------
    # Worker helpers and errors
    # ------------------------------------------------------------------
    def _run_worker(
        self,
        function: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_failure: Callable[[BaseException], None] | None = None,
    ) -> None:
        worker = FunctionWorker(function)
        self._workers.add(worker)

        def success(result: Any) -> None:
            self._workers.discard(worker)
            on_success(result)

        def failure(error: BaseException) -> None:
            self._workers.discard(worker)
            if on_failure is not None:
                on_failure(error)
            else:
                self._show_error(error)

        worker.signals.finished.connect(success)
        worker.signals.failed.connect(failure)
        self.thread_pool.start(worker)

    def _show_error(self, error: BaseException) -> None:
        friendly = friendly_error(error)
        self.log(
            "error",
            "log.error",
            title=friendly.title,
            message=friendly.message,
        )
        if friendly.details:
            self.log(
                "error",
                "log.technical_details",
                details=redact_secrets(friendly.details),
            )

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(friendly.title)
        box.setText(friendly.message)
        if friendly.details:
            box.setInformativeText(tr("common.details_hint"))
            box.setDetailedText(redact_secrets(friendly.details))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    # ------------------------------------------------------------------
    # System checks
    # ------------------------------------------------------------------
    def run_system_check(
        self,
        *,
        show_dialog: bool,
        log_result: bool,
    ) -> None:
        self.system_checks = run_system_checks()
        self._update_system_button()

        problems = sum(
            1
            for check in self.system_checks
            if check.required and not check.ok
        )
        if log_result:
            if problems:
                self.log("warning", "log.system_problem", count=problems)
            else:
                self.log("ok", "log.system_ready")

        if show_dialog:
            SystemCheckDialog(self.system_checks, self).exec()

    def _update_system_button(self) -> None:
        # Keep the native theme button background. Only the status symbol is
        # colored, so light and dark desktop themes remain visually consistent.
        self.system_button.setStyleSheet("")
        self.system_button.setIconSize(QSize(18, 18))

        if not self.system_checks:
            self.system_button.setText(tr("common.checking"))
            self.system_button.setIcon(system_status_icon("checking"))
            return

        problems = sum(
            1
            for check in self.system_checks
            if check.required and not check.ok
        )
        if problems == 0:
            self.system_button.setText(tr("system.ready"))
            self.system_button.setIcon(system_status_icon("ok"))
        else:
            key = "system.problem" if problems == 1 else "system.problems"
            self.system_button.setText(tr(key, count=problems))
            self.system_button.setIcon(system_status_icon("error"))
        self.system_button.setToolTip(tr("system.show_details"))

    # ------------------------------------------------------------------
    # Regions and ping
    # ------------------------------------------------------------------
    def refresh_regions(self) -> None:
        if self._regions_busy:
            return
        self._regions_busy = True
        self._update_controls()
        self.status_detail_label.setText(tr("activity.loading_regions"))
        self.log("info", "activity.loading_regions")

        def job() -> list[Region]:
            return measure_latencies(fetch_regions())

        def success(result: Any) -> None:
            self._regions_busy = False
            self.regions = list(result)
            try:
                save_regions(self.regions)
            except OSError:
                pass
            self._populate_region_combo()
            reachable = sum(
                1 for region in self.regions if region.ping_ms is not None
            )
            self.log(
                "ok",
                "activity.loaded_regions",
                total=len(self.regions),
                reachable=reachable,
            )
            self._update_controls()
            self.update_connection_status(force=True)
            self._rebuild_tray_menu()

        def failure(error: BaseException) -> None:
            self._regions_busy = False
            self.log("error", "activity.regions_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(error)

        self._run_worker(job, on_success=success, on_failure=failure)

    def refresh_pings(self) -> None:
        if self._regions_busy:
            return
        if not self.regions:
            self.refresh_regions()
            return

        self._regions_busy = True
        self._update_controls()
        self.status_detail_label.setText(tr("activity.refreshing_pings"))
        self.log("info", "activity.refreshing_pings")

        current = list(self.regions)

        def job() -> list[Region]:
            return measure_latencies(current)

        def success(result: Any) -> None:
            self._regions_busy = False
            self.regions = list(result)
            try:
                save_regions(self.regions)
            except OSError:
                pass
            self._populate_region_combo()
            reachable = sum(
                1 for region in self.regions if region.ping_ms is not None
            )
            self.log(
                "ok",
                "activity.pings_done",
                reachable=reachable,
            )
            self._update_controls()
            self.update_connection_status(force=True)
            self._rebuild_tray_menu()

        def failure(error: BaseException) -> None:
            self._regions_busy = False
            self.log("error", "activity.pings_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(error)

        self._run_worker(job, on_success=success, on_failure=failure)

    def _populate_region_combo(self) -> None:
        if not hasattr(self, "region_combo"):
            return

        selected_id = str(
            self.settings.value("connection/selected_region_id", FASTEST_ID)
        ).strip() or FASTEST_ID
        current_data = self.region_combo.currentData()
        if current_data:
            selected_id = str(current_data)

        query = self.search_edit.text().strip().casefold()
        filtered = [
            region
            for region in self.regions
            if not query or query in search_haystack(region)
        ]

        self.region_combo.blockSignals(True)
        self.region_combo.clear()

        if not query:
            fastest_text = tr("connection.fastest")
            if self.regions and self.regions[0].ping_ms is not None:
                fastest_text += f" · {self.regions[0].ping_ms:.0f} ms"
            self.region_combo.addItem(f"⚡ {fastest_text}", FASTEST_ID)

        for region in filtered:
            self.region_combo.addItem(
                region_display_name(region, language()),
                region.region_id,
            )

        target_index = self.region_combo.findData(selected_id)
        if target_index < 0 and self.region_combo.count() > 0:
            target_index = 0
        self.region_combo.setCurrentIndex(target_index)
        self.region_combo.blockSignals(False)
        self._update_controls()

    def _selection_changed(self, index: int) -> None:
        if index < 0:
            return
        selected_id = str(self.region_combo.itemData(index))
        self.settings.setValue("connection/selected_region_id", selected_id)
        self.settings.sync()
        self._rebuild_tray_menu()

    def _selected_region(self) -> Region | None:
        if not self.regions:
            return None
        selected_id = str(self.region_combo.currentData() or FASTEST_ID)
        if selected_id == FASTEST_ID:
            return next(
                (region for region in self.regions if region.ping_ms is not None),
                self.regions[0],
            )
        return next(
            (region for region in self.regions if region.region_id == selected_id),
            None,
        )

    def _region_by_id(self, region_id: str) -> Region | None:
        return next(
            (region for region in self.regions if region.region_id == region_id),
            None,
        )

    def _last_selected_region(self) -> Region | None:
        selected_id = str(
            self.settings.value("connection/selected_region_id", FASTEST_ID)
        ).strip() or FASTEST_ID
        if selected_id == FASTEST_ID:
            return self._selected_fastest_region()
        return self._region_by_id(selected_id) or self._selected_fastest_region()

    def _selected_fastest_region(self) -> Region | None:
        if not self.regions:
            return None
        return next(
            (region for region in self.regions if region.ping_ms is not None),
            self.regions[0],
        )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def toggle_connection(self) -> None:
        if self._connection_busy:
            return
        try:
            connected = network_manager.is_connected()
        except BaseException as exc:
            self._show_error(exc)
            return
        if connected:
            self.disconnect()
        else:
            region = self._selected_region()
            if region is None:
                QMessageBox.information(
                    self,
                    tr("connection.no_location_title"),
                    tr("connection.no_location_message"),
                )
                return
            self.connect_region(region)

    def connect_region(self, region: Region) -> None:
        if self._connection_busy:
            return

        if not self.system_checks:
            self.run_system_check(show_dialog=False, log_result=False)
        if not required_checks_pass(self.system_checks):
            QMessageBox.warning(
                self,
                tr("connection.system_not_ready_title"),
                tr("connection.system_not_ready_message"),
            )
            SystemCheckDialog(self.system_checks, self).exec()
            return

        credentials = self._get_credentials()
        if credentials is None:
            return

        try:
            was_connected = network_manager.is_connected()
        except BaseException as exc:
            self._show_error(exc)
            return

        self._connection_busy = True
        self._update_controls()
        region_name = localized_region_name(region, language())
        if was_connected:
            self.status_detail_label.setText(
                tr("activity.switching", region=region_name)
            )
        else:
            self.status_detail_label.setText(
                tr("activity.preparing_connection", region=region_name)
            )
        self.log("info", "log.connecting", region=region_name)

        config_path = cache_dir() / f"{network_manager.INTERFACE_NAME}.conf"

        def job() -> str:
            try:
                create_wireguard_config(
                    config_path=config_path,
                    credentials=credentials,
                    region=region,
                )
                return network_manager.connect(config_path)
            finally:
                try:
                    config_path.unlink(missing_ok=True)
                except OSError:
                    pass

        def success(result: Any) -> None:
            self._connection_busy = False
            profile_uuid = str(result)
            self._active_region_id = region.region_id
            self._active_region_fallback = region.name
            self.settings.setValue(
                "connection/selected_region_id",
                region.region_id,
            )
            self.settings.setValue(
                "connection/active_region_id",
                region.region_id,
            )
            self.settings.setValue(
                "connection/active_region_name",
                region.name,
            )
            self.settings.setValue(
                "connection/profile_uuid",
                profile_uuid,
            )
            self.settings.sync()
            self.log("ok", "log.connected", region=region_name)
            self._update_controls()
            self.update_connection_status(force=True)
            self.refresh_public_info(show_errors=False)
            self._rebuild_tray_menu()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self.log("error", "activity.connection_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(error)

        self._run_worker(job, on_success=success, on_failure=failure)

    def disconnect(self, *, after_disconnect: Callable[[], None] | None = None) -> None:
        if self._connection_busy:
            return

        self._connection_busy = True
        self._update_controls()
        self.status_detail_label.setText(tr("activity.disconnecting"))
        self.log("info", "activity.disconnecting")

        profile_uuid = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()

        def job() -> None:
            network_manager.disconnect(profile_uuid)

        def success(_: Any) -> None:
            self._connection_busy = False
            self.settings.remove("connection/profile_uuid")
            self.settings.sync()
            self.log("ok", "log.disconnected")
            self._update_controls()
            self.update_connection_status(force=True)
            self.refresh_public_info(show_errors=False)
            self._rebuild_tray_menu()
            if after_disconnect is not None:
                after_disconnect()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self.log("error", "activity.disconnect_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(error)

        self._run_worker(job, on_success=success, on_failure=failure)

    def update_connection_status(self, force: bool = False) -> None:
        if self._stage4_preview:
            self._set_stage4_preview_state(
                self._stage4_preview_index,
                log_transition=False,
            )
            return
        try:
            connected = network_manager.is_connected()
        except BaseException:
            connected = False

        changed = (
            self._last_connected_state is None
            or connected != self._last_connected_state
        )
        previous = self._last_connected_state
        self._last_connected_state = connected

        state = self.kill_switch_runtime.view_state(
            vpn_connected=connected,
        )
        self._apply_kill_switch_view_state(
            state,
            log_transition=not self._connection_busy,
        )

        if connected:
            self.ipv6_value.setText(
                tr("status.ipv6_blocked")
                if network_manager.ipv6_blackhole_active()
                else tr("status.ipv6_warning")
            )
            self.dns_value.setText(tr("status.dns_pia"))
            self.connection_button.setText(tr("connection.disconnect"))
            self.toggle_vpn_action.setText(tr("connection.disconnect"))
        else:
            self.ipv6_value.setText(tr("status.ipv6_normal"))
            self.dns_value.setText(tr("status.dns_system"))
            self.connection_button.setText(tr("connection.connect"))
            self.toggle_vpn_action.setText(tr("connection.connect"))

        if self.public_info is None:
            self.ip_value.setText(tr("common.checking"))
            self.country_value.setText(tr("common.checking"))
        else:
            self.ip_value.setText(self.public_info.ip_address)
            self.country_value.setText(
                public_country_name(self.public_info.country_code, language())
            )

        if changed and previous is not None and not self._connection_busy:
            self.log(
                "info",
                "log.external_connected" if connected else "log.external_disconnected",
            )
            self.refresh_public_info(show_errors=False)

        self._update_controls()
        if force or changed:
            self._rebuild_tray_menu()

    def _update_controls(self) -> None:
        if self._stage4_preview:
            return
        busy = self._connection_busy or self._regions_busy
        has_regions = bool(self.regions)
        try:
            connected = network_manager.is_connected()
        except BaseException:
            connected = False

        self.connection_button.setEnabled(
            not busy and (has_regions or connected)
        )
        self.region_combo.setEnabled(not busy and has_regions)
        self.search_edit.setEnabled(not busy and has_regions)
        self.reload_button.setEnabled(not busy)
        self.ping_button.setEnabled(not busy and has_regions)
        self.ip_refresh_button.setEnabled(not self._public_info_busy)
        self.reload_action.setEnabled(not busy)
        self.ping_action.setEnabled(not busy and has_regions)
        self.toggle_vpn_action.setEnabled(not self._connection_busy)

    # ------------------------------------------------------------------
    # Public network information
    # ------------------------------------------------------------------
    def refresh_public_info(self, *, show_errors: bool) -> None:
        if self._public_info_busy:
            return
        self._public_info_busy = True
        self.ip_value.setText(tr("common.checking"))
        self.country_value.setText(tr("common.checking"))
        self.ip_refresh_button.setEnabled(False)

        def success(result: Any) -> None:
            self._public_info_busy = False
            self.public_info = result
            self.ip_value.setText(result.ip_address)
            self.country_value.setText(
                public_country_name(result.country_code, language())
            )
            self.ip_refresh_button.setEnabled(True)
            self.log(
                "info",
                "log.public_info",
                ip=mask_ip_address(result.ip_address),
                country=public_country_name(result.country_code, language()),
            )

        def failure(error: BaseException) -> None:
            self._public_info_busy = False
            self.ip_value.setText(tr("status.ip_unavailable"))
            self.country_value.setText(tr("common.unknown"))
            self.ip_refresh_button.setEnabled(True)
            self.log("warning", "log.public_info_failed")
            if show_errors:
                self._show_error(error)

        self._run_worker(
            fetch_public_network_info,
            on_success=success,
            on_failure=failure,
        )

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    def _rebuild_tray_menu(self) -> None:
        if not hasattr(self, "tray"):
            return

        if self._stage4_preview:
            menu = QMenu()
            state = self._kill_switch_view_state
            status_action = QAction(tr(state.tray_status_key), menu)
            status_action.setIcon(status_dot_icon(state.icon_state))
            status_action.setEnabled(False)
            menu.addAction(status_action)
            menu.addSeparator()
            show_action = QAction(tr("tray.show"), menu)
            show_action.triggered.connect(self.show_window)
            menu.addAction(show_action)
            quit_action = QAction(tr("tray.quit"), menu)
            quit_action.triggered.connect(self.request_quit)
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self._tray_menu = menu
            self.tray.setIcon(status_icon(state.icon_state))
            self.tray.setToolTip(tr(state.tray_tooltip_key))
            return

        menu = QMenu()
        try:
            connected = network_manager.is_connected()
        except BaseException:
            connected = False

        state = self._kill_switch_view_state
        status_action = QAction(tr(state.tray_status_key), menu)
        status_action.setIcon(status_dot_icon(state.icon_state))
        # Indicator only: one colored icon, no duplicate text bullet, and no
        # click action.
        status_action.setEnabled(False)
        menu.addAction(status_action)
        menu.addSeparator()

        if connected:
            disconnect_action = QAction(tr("connection.disconnect"), menu)
            disconnect_action.setEnabled(not self._connection_busy)
            disconnect_action.triggered.connect(
                lambda checked=False: self.disconnect()
            )
            menu.addAction(disconnect_action)
        else:
            last_region = self._last_selected_region()
            connect_action = QAction(menu)
            if last_region is None:
                connect_action.setText(tr("tray.locations_unavailable"))
                connect_action.setEnabled(False)
            else:
                selected_id = str(
                    self.settings.value(
                        "connection/selected_region_id",
                        FASTEST_ID,
                    )
                )
                if selected_id == FASTEST_ID:
                    connect_action.setText(tr("tray.connect_fastest"))
                else:
                    connect_action.setText(
                        tr(
                            "tray.connect_last",
                            region=localized_region_name(last_region, language()),
                        )
                    )
                connect_action.setEnabled(not self._connection_busy)
                connect_action.triggered.connect(
                    lambda checked=False, region=last_region: self.connect_region(region)
                )
            menu.addAction(connect_action)

        locations_menu = menu.addMenu(
            tr("tray.switch_server") if connected else tr("tray.connect_with")
        )
        locations_menu.setEnabled(bool(self.regions) and not self._connection_busy)

        fastest = self._selected_fastest_region()
        if fastest is not None:
            fastest_action = QAction(
                f"⚡ {tr('connection.fastest')}"
                + (
                    f" · {fastest.ping_ms:.0f} ms"
                    if fastest.ping_ms is not None
                    else ""
                ),
                locations_menu,
            )
            fastest_action.triggered.connect(
                lambda checked=False, region=fastest: self.connect_region(region)
            )
            locations_menu.addAction(fastest_action)
            locations_menu.addSeparator()

            reachable = [
                region
                for region in self.regions
                if region.ping_ms is not None
                and region.region_id != fastest.region_id
            ][:10]
            for region in reachable:
                action = QAction(
                    region_display_name(region, language()),
                    locations_menu,
                )
                action.triggered.connect(
                    lambda checked=False, selected=region: self.connect_region(selected)
                )
                locations_menu.addAction(action)

            locations_menu.addSeparator()

        full_list_action = QAction(tr("tray.full_list"), locations_menu)
        full_list_action.triggered.connect(self.show_full_server_list)
        locations_menu.addAction(full_list_action)

        menu.addSeparator()
        show_action = QAction(tr("tray.show"), menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)

        quit_action = QAction(tr("tray.quit"), menu)
        quit_action.triggered.connect(self.request_quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self._tray_menu = menu

        self.tray.setIcon(status_icon(state.icon_state))
        self.tray.setToolTip(tr(state.tray_tooltip_key))

    def _tray_setting_changed(self, checked: bool) -> None:
        self.settings.setValue("ui/tray_enabled", checked)
        self.settings.sync()
        self._apply_tray_setting(log_change=True)

    def _apply_tray_setting(self, *, log_change: bool) -> None:
        if self._stage4_preview:
            self.tray.hide()
            return
        enabled = bool_value(self.settings, "ui/tray_enabled", True)

        if enabled and not QSystemTrayIcon.isSystemTrayAvailable():
            enabled = False
            self.settings.setValue("ui/tray_enabled", False)
            self.settings.sync()
            self.tray_action.blockSignals(True)
            self.tray_action.setChecked(False)
            self.tray_action.blockSignals(False)
            self.tray.hide()
            QMessageBox.warning(
                self,
                tr("tray.unavailable_title"),
                tr("tray.unavailable_message"),
            )
            return

        self.tray_action.blockSignals(True)
        self.tray_action.setChecked(enabled)
        self.tray_action.blockSignals(False)

        if enabled:
            self.tray.show()
            if log_change:
                self.log("info", "log.tray_enabled")
        else:
            self.tray.hide()
            if log_change:
                self.log("info", "log.tray_disabled")

    def _tray_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        # Plasma opens the native context menu for a context click. A normal
        # click only raises the existing main window and never opens a manual
        # popup, avoiding Wayland grabbing errors.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_full_server_list(self) -> None:
        self.show_window()
        self.search_edit.clear()
        self.region_combo.setFocus()
        self.region_combo.showPopup()

    # ------------------------------------------------------------------
    # Live log and window sizing
    # ------------------------------------------------------------------
    def _set_live_log_visible(self, visible: bool) -> None:
        if self.log_panel.isVisible() == visible:
            return
        self.log_panel.setVisible(visible)
        self._log_visibility_changed(visible)

    def _log_visibility_changed(self, visible: bool) -> None:
        self.live_log_action.blockSignals(True)
        self.live_log_action.setChecked(visible)
        self.live_log_action.blockSignals(False)
        self.settings.setValue("ui/live_log", visible)

        # Both modes are intentionally fixed-size. The expanded mode only
        # adds the log immediately below the connection section.
        target = LOG_SIZE if visible else COMPACT_SIZE
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.setFixedSize(target)
        self.settings.sync()

    def _apply_live_log_setting(self, *, initial: bool) -> None:
        del initial
        visible = bool_value(self.settings, "ui/live_log", False)
        self.live_log_action.blockSignals(True)
        self.live_log_action.setChecked(visible)
        self.live_log_action.blockSignals(False)
        self.log_panel.setVisible(visible)
        self.setFixedSize(LOG_SIZE if visible else COMPACT_SIZE)

    # ------------------------------------------------------------------
    # About and application lifecycle
    # ------------------------------------------------------------------
    def show_about(self) -> None:
        QMessageBox.about(
            self,
            tr("about.title"),
            tr("about.body", version=__version__),
        )

    def show_window(self) -> None:
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.raise_()
        self.activateWindow()

    def request_quit(self) -> None:
        if self._stage4_preview:
            self._final_quit()
            return
        if self._connection_busy:
            QMessageBox.information(
                self,
                tr("quit.busy_title"),
                tr("quit.busy_message"),
            )
            return

        try:
            connected = network_manager.is_connected()
        except BaseException:
            connected = False

        if not connected:
            self._final_quit()
            return

        behavior = str(self.settings.value("ui/quit_behavior", "ask"))
        if behavior not in {"ask", "disconnect", "leave"}:
            behavior = "ask"

        if behavior == "ask":
            dialog = QuitDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            behavior = dialog.choice
            if dialog.remember_checkbox.isChecked():
                self.settings.setValue("ui/quit_behavior", behavior)
                self.settings.sync()
                self.retranslate()

        if behavior == "leave":
            self._final_quit()
        elif behavior == "disconnect":
            self.disconnect(after_disconnect=self._final_quit)

    def _final_quit(self) -> None:
        self._allow_close = True
        self.tray.hide()
        self.status_timer.stop()
        self.app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._stage4_preview:
            self._allow_close = True
            event.accept()
            self.tray.hide()
            self.app.quit()
            return
        if self._allow_close:
            event.accept()
            return

        tray_enabled = bool_value(self.settings, "ui/tray_enabled", True)
        if tray_enabled and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._close_hint_shown:
                self._close_hint_shown = True
                self.tray.showMessage(
                    tr("tray.hidden_title"),
                    tr("tray.hidden_message"),
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            return

        event.ignore()
        self.request_quit()
