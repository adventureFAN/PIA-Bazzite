from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QSettings, QSize, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import __app_id__, __version__, network_manager
from .app_errors import AppError, friendly_error
from .credentials import CredentialStore, Credentials
from .emergency_reset import EmergencyResetResult, run_verified_emergency_reset
from .i18n import language, set_language, tr
from .host_open import open_host_target
from .helper_installation import (
    HelperInstallationAudit,
    HelperInstallationState,
    PackagedHelperManager,
)
from .icons import status_dot_icon, status_icon, system_status_icon
from .logging_utils import mask_ip_address, redact_secrets
from .kill_switch_client import (
    AuthorizationDeniedError,
    IPv6GuardStatus,
    KillSwitchClient,
    KillSwitchClientError,
    KillSwitchStatus,
)
from .kill_switch_crash_state import (
    CrashRecoveryDecision,
    CrashRecoveryDisposition,
    CrashRecoveryJournal,
    CrashRecoveryStateError,
    CrashRecoveryStore,
    CrashRecoveryVerifier,
)
from .kill_switch_connection import (
    ConnectionEvent,
    ConnectionPhase,
    ConnectionPlan,
    IntentionalDisconnectError,
    KillSwitchConnectionOrchestrator,
    KillSwitchPreparationError,
    PostConnectVerificationError,
    VpnStartError,
    read_wireguard_endpoint,
)
from .kill_switch_recovery import (
    FirewallRoutePlan,
    KillSwitchRecoveryOrchestrator,
    PreparedServerSwitch,
    ProtectedReconnectError,
    ProtectedServerSwitchError,
    RecoveryEvent,
    RecoveryPhase,
)
from .kill_switch_runtime import KillSwitchRuntimeController
from .kill_switch_session import KillSwitchSessionClient
from .kill_switch_state import (
    KillSwitchObservation,
    KillSwitchViewState,
    derive_kill_switch_view_state,
    sample_kill_switch_states,
)
from .kill_switch_widgets import KillSwitchStatusWidget
from .ipv6_guard_lifecycle import (
    GuardStartupResult,
    IPv6GuardConnectError,
    IPv6GuardDisconnectError,
    IPv6GuardLifecycle,
    IPv6GuardLifecycleError,
    IPv6GuardStartupError,
)
from .models import PublicNetworkInfo, Region, SystemCheck
from .network_paths import discover_physical_interface
from .network_probes import NetworkProbeBaseline, NetworkProbeError
from .pia_api import (
    create_wireguard_config,
    fetch_public_network_info,
    fetch_regions,
    measure_latencies,
)
from .region_cache import load_regions, save_regions
from .region_favorites import (
    MAX_FAVORITE_REGIONS,
    FavoriteAddResult,
    FavoriteRegion,
    FavoriteRegionStore,
)
from .region_names import (
    localized_region_name,
    public_country_name,
    region_display_name,
    search_haystack,
)
from .settings import bool_value, cache_dir, crash_recovery_path, state_dir
from .system_checks import required_checks_pass, run_system_checks
from .theme import ThemeController
from .workers import FunctionWorker


FASTEST_ID = "__fastest__"
COMPACT_SIZE = QSize(740, 510)
LOG_SIZE = QSize(760, 780)
REGION_POPUP_VISIBLE_ITEMS = 20
REGION_FAVORITE_TOGGLE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
REGION_FAVORITE_AVAILABLE_ROLE = int(Qt.ItemDataRole.UserRole) + 2
REGION_FAVORITE_STAR_HIT_WIDTH = 34
REGION_MARKER_ICON_SIZE = QSize(18, 18)
REGION_MARKER_ACCENT_COLOR = "#f4c542"
PROJECT_URL = "https://github.com/adventureFAN/PIA-Bazzite"
KILL_SWITCH_RECONCILIATION_REQUIRED_KEY = "kill_switch/reconciliation_required"


class RegionComboBox(QComboBox):
    """Region selector with a separately clickable favorite-star hit target.

    The popup still uses the normal QComboBox/QAbstractItemView selection path.
    Only clicks inside the small star area are intercepted, so toggling a
    favorite cannot accidentally activate a server or trigger a server switch.
    The event filter also receives clicks on disabled rows, which lets a
    catalog-missing favorite remain non-connectable while its star can still be
    removed by the user.
    """

    favoriteToggled = Signal(str)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._favorite_press_region_id = ""
        self.setIconSize(REGION_MARKER_ICON_SIZE)
        self.view().viewport().installEventFilter(self)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        viewport = self.view().viewport()
        event_type = event.type()
        is_mouse_event = event_type in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        }
        if watched is viewport and is_mouse_event:
            if event.button() != Qt.MouseButton.LeftButton:
                return super().eventFilter(watched, event)

            point = event.position().toPoint()
            index = self.view().indexAt(point)
            in_star = False
            region_id = ""
            if index.isValid() and bool(index.data(REGION_FAVORITE_TOGGLE_ROLE)):
                rect = self.view().visualRect(index)
                in_star = (
                    rect.left() <= point.x() <= rect.left() + REGION_FAVORITE_STAR_HIT_WIDTH
                )
                region_id = str(index.data(Qt.ItemDataRole.UserRole) or "").strip()

            if event_type == QEvent.Type.MouseButtonPress:
                self._favorite_press_region_id = region_id if in_star else ""
                if in_star and region_id:
                    return True
            else:
                pressed_region_id = self._favorite_press_region_id
                self._favorite_press_region_id = ""
                if in_star and region_id and region_id == pressed_region_id:
                    QTimer.singleShot(
                        0,
                        lambda selected=region_id: self.favoriteToggled.emit(selected),
                    )
                    return True

        return super().eventFilter(watched, event)

    def set_region_row_available(self, row: int, available: bool) -> None:
        self.setItemData(row, bool(available), REGION_FAVORITE_AVAILABLE_ROLE)
        model = self.model()
        item_getter = getattr(model, "item", None)
        item = item_getter(row) if callable(item_getter) else None
        if item is not None:
            item.setEnabled(bool(available))

    def showPopup(self) -> None:
        super().showPopup()
        QTimer.singleShot(0, self._prepare_popup)

    def _prepare_popup(self) -> None:
        self._limit_popup_height()
        self.view().scrollToTop()

    def _limit_popup_height(self) -> None:
        view = self.view()
        visible = min(self.count(), REGION_POPUP_VISIBLE_ITEMS)
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


_CONNECTION_EVENT_LOG_KEYS: dict[ConnectionPhase, str] = {
    ConnectionPhase.PLAN_VALIDATED: "log.kill_switch.connection.plan_validated",
    ConnectionPhase.KILL_SWITCH_BYPASSED: "log.kill_switch.connection.bypassed",
    ConnectionPhase.AUTHORIZATION_STARTED: "log.kill_switch.connection.authorization",
    ConnectionPhase.SESSION_AUTHORIZED: "log.kill_switch.connection.session_ready",
    ConnectionPhase.FIREWALL_PREPARED: "log.kill_switch.connection.firewall_prepared",
    ConnectionPhase.VPN_STARTING: "log.kill_switch.connection.vpn_starting",
    ConnectionPhase.VPN_STARTED: "log.kill_switch.connection.vpn_started",
    ConnectionPhase.POSTCHECK_STARTED: "log.kill_switch.connection.postcheck",
    ConnectionPhase.CONNECTION_VERIFIED: "log.kill_switch.connection.verified",
    ConnectionPhase.ROLLBACK_STARTED: "log.kill_switch.connection.rollback_started",
    ConnectionPhase.ROLLBACK_COMPLETED: "log.kill_switch.connection.rollback_done",
    ConnectionPhase.DISCONNECT_PREFLIGHT_STARTED: "log.kill_switch.disconnect.preflight",
    ConnectionPhase.DISCONNECT_PREFLIGHT_VERIFIED: "log.kill_switch.disconnect.lock_verified",
    ConnectionPhase.VPN_STOPPING: "log.kill_switch.disconnect.vpn_stopping",
    ConnectionPhase.VPN_STOPPED: "log.kill_switch.disconnect.vpn_stopped",
    ConnectionPhase.BLOCKED_PATH_CHECK_STARTED: "log.kill_switch.disconnect.probe_started",
    ConnectionPhase.BLOCKED_PATH_VERIFIED: "log.kill_switch.disconnect.probe_verified",
    ConnectionPhase.FIREWALL_RELEASING: "log.kill_switch.disconnect.releasing",
    ConnectionPhase.FIREWALL_RELEASED: "log.kill_switch.disconnect.released",
    ConnectionPhase.INTENTIONAL_DISCONNECT_VERIFIED: "log.kill_switch.disconnect.verified",
}


_RECOVERY_EVENT_LOG_KEYS: dict[RecoveryPhase, str] = {
    RecoveryPhase.RECONNECT_PREFLIGHT_STARTED: "log.kill_switch.recovery.reconnect_preflight",
    RecoveryPhase.RECONNECT_PREFLIGHT_VERIFIED: "log.kill_switch.recovery.reconnect_ready",
    RecoveryPhase.SWITCH_PREFLIGHT_STARTED: "log.kill_switch.recovery.switch_preflight",
    RecoveryPhase.SWITCH_PREFLIGHT_VERIFIED: "log.kill_switch.recovery.switch_ready",
    RecoveryPhase.OLD_VPN_STOPPING: "log.kill_switch.recovery.old_vpn_stopping",
    RecoveryPhase.OLD_VPN_STOPPED: "log.kill_switch.recovery.old_vpn_stopped",
    RecoveryPhase.BLOCKED_PATH_CHECK_STARTED: "log.kill_switch.recovery.probe_started",
    RecoveryPhase.BLOCKED_PATH_VERIFIED: "log.kill_switch.recovery.probe_verified",
    RecoveryPhase.NEW_ROUTE_RESOLVING: "log.kill_switch.recovery.route_resolving",
    RecoveryPhase.NEW_ROUTE_RESOLVED: "log.kill_switch.recovery.route_resolved",
    RecoveryPhase.FIREWALL_RETARGET_STARTED: "log.kill_switch.recovery.firewall_updating",
    RecoveryPhase.FIREWALL_RETARGETED: "log.kill_switch.recovery.firewall_updated",
    RecoveryPhase.VPN_RECONNECTING: "log.kill_switch.recovery.reconnecting",
    RecoveryPhase.VPN_RECONNECTED: "log.kill_switch.recovery.reconnected",
    RecoveryPhase.NEW_VPN_STARTING: "log.kill_switch.recovery.new_vpn_starting",
    RecoveryPhase.NEW_VPN_STARTED: "log.kill_switch.recovery.new_vpn_started",
    RecoveryPhase.POSTCHECK_STARTED: "log.kill_switch.recovery.postcheck",
    RecoveryPhase.RECONNECT_VERIFIED: "log.kill_switch.recovery.reconnect_verified",
    RecoveryPhase.SWITCH_VERIFIED: "log.kill_switch.recovery.switch_verified",
    RecoveryPhase.ROLLBACK_STARTED: "log.kill_switch.recovery.rollback_started",
    RecoveryPhase.ROLLBACK_COMPLETED: "log.kill_switch.recovery.rollback_done",
}


@dataclass(frozen=True, slots=True)
class _ProtectedConnectOutcome:
    profile_uuid: str
    session: KillSwitchSessionClient
    status: KillSwitchStatus
    baseline: NetworkProbeBaseline
    route_plan: FirewallRoutePlan
    events: tuple[ConnectionEvent, ...]


@dataclass(frozen=True, slots=True)
class _ProtectedDisconnectOutcome:
    session: KillSwitchSessionClient
    status: KillSwitchStatus
    events: tuple[ConnectionEvent, ...]


@dataclass(frozen=True, slots=True)
class _NormalGuardConnectOutcome:
    profile_uuid: str
    session: KillSwitchSessionClient
    status: IPv6GuardStatus


@dataclass(frozen=True, slots=True)
class _NormalGuardDisconnectOutcome:
    session: KillSwitchSessionClient
    status: IPv6GuardStatus


@dataclass(frozen=True, slots=True)
class _NormalGuardStartupOutcome:
    session: KillSwitchSessionClient
    result: GuardStartupResult


class _IPv6GuardJobFailure(RuntimeError):
    def __init__(
        self,
        cause: BaseException,
        *,
        session: KillSwitchSessionClient | None,
        status: IPv6GuardStatus | None,
        status_error: str = "",
        guard_retained: bool = True,
        vpn_connected: bool | None = None,
    ) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.session = session
        self.status = status
        self.status_error = status_error.strip()
        self.guard_retained = bool(guard_retained)
        self.vpn_connected = vpn_connected


@dataclass(frozen=True, slots=True)
class _ProtectedReconnectOutcome:
    profile_uuid: str
    session: KillSwitchSessionClient
    status: KillSwitchStatus
    route_plan: FirewallRoutePlan
    events: tuple[RecoveryEvent, ...]


@dataclass(frozen=True, slots=True)
class _ProtectedServerSwitchOutcome:
    profile_uuid: str
    session: KillSwitchSessionClient
    status: KillSwitchStatus
    route_plan: FirewallRoutePlan
    events: tuple[RecoveryEvent, ...]


@dataclass(frozen=True, slots=True)
class _KillSwitchAuthorizationOutcome:
    session: KillSwitchSessionClient
    status: KillSwitchStatus


@dataclass(frozen=True, slots=True)
class _KillSwitchStatusRecheckOutcome:
    status: KillSwitchStatus


@dataclass(frozen=True, slots=True)
class _KillSwitchStartupRecoveryOutcome:
    session: KillSwitchSessionClient
    status: KillSwitchStatus
    decision: CrashRecoveryDecision


class _KillSwitchJobFailure(RuntimeError):
    def __init__(
        self,
        cause: BaseException,
        *,
        session: KillSwitchSessionClient | None = None,
        status: KillSwitchStatus | None = None,
        status_error: str = "",
        baseline: NetworkProbeBaseline | None = None,
        route_plan: FirewallRoutePlan | None = None,
        events: tuple[ConnectionEvent, ...] = (),
    ) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.session = session
        self.status = status
        self.status_error = status_error.strip()
        self.baseline = baseline
        self.route_plan = route_plan
        self.events = events


class _KillSwitchRecoveryJobFailure(RuntimeError):
    def __init__(
        self,
        cause: BaseException,
        *,
        session: KillSwitchSessionClient | None,
        status: KillSwitchStatus | None,
        status_error: str,
        route_plan: FirewallRoutePlan | None,
        baseline: NetworkProbeBaseline | None,
        events: tuple[RecoveryEvent, ...],
    ) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.session = session
        self.status = status
        self.status_error = status_error.strip()
        self.route_plan = route_plan
        self.baseline = baseline
        self.events = events


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


class ThirdPartyNoticesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("about.third_party_title"))
        self.resize(720, 520)

        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setMarkdown(self._read_notices())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(tr("common.close"))
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(view, 1)
        layout.addWidget(buttons)

    @staticmethod
    def _read_notices() -> str:
        candidates = (
            Path(__file__).resolve().parent / "resources" / "THIRD_PARTY_NOTICES.md",
            Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md",
        )
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.read_text(encoding="utf-8")
            except OSError:
                continue
        return tr("about.third_party_unavailable")


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(570)

        icon_label = QLabel()
        icon_label.setPixmap(status_icon("application", 104).pixmap(104, 104))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name_label = QLabel("PIA Bazzite")
        name_font = name_label.font()
        name_font.setPixelSize(24)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        version_label = QLabel(tr("about.version", version=__version__))
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        description_label = QLabel(tr("about.description"))
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label.setWordWrap(True)

        license_label = QLabel(f"<i>{escape(tr('about.license'))}</i>")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        developer_label = QLabel(tr("about.developer"))
        developer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        developer_label.setWordWrap(True)

        disclaimer_label = QLabel(tr("about.disclaimer"))
        disclaimer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disclaimer_label.setWordWrap(True)

        project_button = QPushButton(tr("about.project_page"))
        project_button.clicked.connect(lambda: open_host_target(PROJECT_URL))

        notices_button = QPushButton(tr("about.third_party_notices"))
        notices_button.clicked.connect(
            lambda: ThirdPartyNoticesDialog(self).exec()
        )

        close_button = QPushButton(tr("common.close"))
        close_button.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.addWidget(project_button)
        button_row.addWidget(notices_button)
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)
        layout.addWidget(icon_label)
        layout.addWidget(name_label)
        layout.addWidget(version_label)
        layout.addSpacing(4)
        layout.addWidget(description_label)
        layout.addWidget(license_label)
        layout.addWidget(developer_label)
        layout.addWidget(disclaimer_label)
        layout.addSpacing(6)
        layout.addLayout(button_row)


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
        self.region_favorites = FavoriteRegionStore(settings)
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: set[FunctionWorker] = set()
        self._stage4_preview = bool(stage4_preview)
        self._stage4_preview_states = sample_kill_switch_states()
        self._stage4_preview_index = 0
        self._kill_switch_view_state: KillSwitchViewState = (
            self._stage4_preview_states[0]
        )
        self._last_kill_switch_mode: str | None = None
        self._kill_switch_session: KillSwitchSessionClient | None = None
        self._ipv6_guard_session: KillSwitchSessionClient | None = None
        self._packaged_helper_manager = PackagedHelperManager.from_environment()
        self._kill_switch_status: KillSwitchStatus | None = None
        self._ipv6_guard_status: IPv6GuardStatus | None = None
        self._ipv6_guard_status_error = ""
        self._ipv6_guard_release_scheduled = False
        self._kill_switch_status_error = ""
        self._kill_switch_probe_baseline: NetworkProbeBaseline | None = None
        self._kill_switch_route_plan: FirewallRoutePlan | None = None
        self._crash_recovery_journal = CrashRecoveryJournal(
            CrashRecoveryStore(crash_recovery_path())
        )
        self._protected_reconnect_scheduled = False
        self._region_selection_guard = False
        runtime_status_reader = (
            kill_switch_status_reader
            if kill_switch_status_reader is not None
            else self._read_cached_kill_switch_status
        )
        self.kill_switch_runtime = KillSwitchRuntimeController(
            settings,
            status_reader=runtime_status_reader,
        )

        self.session_credentials: Credentials | None = None
        self.regions: list[Region] = load_regions()
        self.system_checks: list[SystemCheck] = []
        self.public_info: PublicNetworkInfo | None = None

        self._connection_busy = False
        self._intentional_disconnect_in_progress = False
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
        self._initial_region_refresh_pending = False

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
        QTimer.singleShot(75, self._reconcile_kill_switch_startup)
        QTimer.singleShot(225, self._reconcile_ipv6_guard_startup)

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

        self.kill_switch_action = QAction(self)
        self.kill_switch_action.setCheckable(True)
        self.kill_switch_action.triggered.connect(self.change_kill_switch_enabled)

        self.about_action = QAction(self)
        self.about_action.setShortcut(QKeySequence("F1"))
        self.about_action.triggered.connect(self.show_about)

        self.emergency_reset_action = QAction(self)
        self.emergency_reset_action.setVisible(False)
        self.emergency_reset_action.triggered.connect(self.emergency_reset)

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

        self.options_menu.addAction(self.kill_switch_action)
        self.options_menu.addSeparator()
        self.options_menu.addAction(self.credentials_action)
        self.options_menu.addAction(self.live_log_action)
        self.options_menu.addAction(self.tray_action)

        self.help_menu = self.menuBar().addMenu("")
        self.help_menu.addAction(self.emergency_reset_action)
        self.help_menu.addSeparator()
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
        self.ip_refresh_button.setFixedSize(24, 22)
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

        self.region_combo = RegionComboBox()
        self.region_combo.setMinimumHeight(38)
        self.region_combo.setMaxVisibleItems(REGION_POPUP_VISIBLE_ITEMS)
        self.region_combo.currentIndexChanged.connect(self._selection_changed)
        self.region_combo.favoriteToggled.connect(self._toggle_region_favorite)
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
        buttons.setContentsMargins(0, 8, 0, 0)
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

    def _read_cached_kill_switch_status(self) -> KillSwitchStatus:
        if self._kill_switch_status_error:
            raise KillSwitchClientError(self._kill_switch_status_error)
        if self._kill_switch_status is None:
            raise KillSwitchClientError(
                "No verified kill-switch helper status is available in this app session."
            )
        return self._kill_switch_status

    def _set_cached_kill_switch_status(
        self,
        status: KillSwitchStatus | None,
        *,
        error: str = "",
    ) -> None:
        self._kill_switch_status = status
        self._kill_switch_status_error = error.strip()

    def _set_cached_ipv6_guard_status(
        self,
        status: IPv6GuardStatus | None,
        *,
        error: str = "",
    ) -> None:
        self._ipv6_guard_status = status
        self._ipv6_guard_status_error = error.strip()

    def _ipv6_guard_expected(self) -> bool:
        return bool_value(
            self.settings,
            "connection/ipv6_guard_expected",
            False,
        )

    def _set_ipv6_guard_expected(self, expected: bool) -> None:
        if expected:
            self.settings.setValue("connection/ipv6_guard_expected", True)
        else:
            self.settings.remove("connection/ipv6_guard_expected")
        self.settings.sync()

    def _close_ipv6_guard_session(self) -> None:
        session = self._ipv6_guard_session
        self._ipv6_guard_session = None
        if session is None:
            return
        try:
            session.close()
        except Exception:
            pass

    def _save_connected_crash_recovery_record(
        self,
        *,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
    ) -> None:
        self._crash_recovery_journal.save_connected(
            profile_uuid=profile_uuid,
            route_plan=route_plan,
        )

    def _save_blocking_crash_recovery_record(
        self,
        *,
        profile_uuid: str,
        route_plan: FirewallRoutePlan,
    ) -> None:
        self._crash_recovery_journal.save_blocking(
            profile_uuid=profile_uuid,
            route_plan=route_plan,
        )

    def _clear_crash_recovery_record(self) -> None:
        self._crash_recovery_journal.clear()

    def _clear_crash_recovery_record_after_safe_release(self) -> None:
        try:
            self._crash_recovery_journal.store.discard_untrusted_after_verified_release()
        except CrashRecoveryStateError as exc:
            self.log(
                "warning",
                "log.kill_switch.crash_record.clear_failed",
                details=str(exc),
            )
        else:
            self._set_kill_switch_reconciliation_marker(False)
            self.log("ok", "log.kill_switch.crash_record.cleared")

    def _protected_reconnect_context_available(self) -> bool:
        profile_uuid = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()
        return (
            bool(profile_uuid)
            and self._kill_switch_probe_baseline is not None
            and self._kill_switch_route_plan is not None
        )

    def _kill_switch_reconciliation_marker_required(self) -> bool:
        return bool_value(
            self.settings,
            KILL_SWITCH_RECONCILIATION_REQUIRED_KEY,
            False,
        )

    def _set_kill_switch_reconciliation_marker(self, required: bool) -> None:
        if required:
            self.settings.setValue(KILL_SWITCH_RECONCILIATION_REQUIRED_KEY, True)
        else:
            self.settings.remove(KILL_SWITCH_RECONCILIATION_REQUIRED_KEY)
        self.settings.sync()

    def _startup_kill_switch_reconciliation_required(self) -> bool:
        record_path = crash_recovery_path()
        return self._kill_switch_reconciliation_marker_required() or (
            record_path.exists() or record_path.is_symlink()
        )

    def _reconcile_kill_switch_startup(self, *, _helper_checked: bool = False) -> None:
        """Adopt only an exactly verified crash-surviving protection state.

        The startup check is automatic only when a crash-recovery record or the
        pre-firewall reconciliation marker says that a production firewall may
        still exist.  Merely remembering the Kill Switch preference while the
        VPN is cleanly disconnected does not require Polkit.  Reconciliation is
        read-only with respect to NetworkManager and nftables: the only permitted
        mutation is clearing already validated stale user state after the helper
        proves the table absent, or rotating the record session ID after exact
        adoption.
        """

        if (
            self._stage4_preview
            or self._connection_busy
            or not self._startup_kill_switch_reconciliation_required()
        ):
            return

        if not _helper_checked:
            self._ensure_packaged_kill_switch_helper(
                on_ready=lambda: self._reconcile_kill_switch_startup(_helper_checked=True),
                on_cancel=self._mark_packaged_helper_unavailable_for_startup,
            )
            return

        self._connection_busy = True
        self._update_controls()
        self.log("info", "log.kill_switch.startup_recovery.started")

        def job() -> _KillSwitchStartupRecoveryOutcome:
            session = KillSwitchSessionClient(timeout=120.0)
            status: KillSwitchStatus | None = None
            try:
                record = self._crash_recovery_journal.store.load()
                session.open()
                first_status = session.status()
                first_network = network_manager.connection_state()
                second_status = session.status()
                second_network = network_manager.connection_state()
                status = second_status
                if first_status != second_status or first_network != second_network:
                    raise CrashRecoveryStateError(
                        "The host protection state changed during startup reconciliation."
                    )

                decision = CrashRecoveryVerifier().evaluate(
                    record=record,
                    helper_status=second_status,
                    vpn_connected=second_network.connected,
                    active_profile_uuid=second_network.uuid,
                )
                # The worker deliberately leaves the recovery record unchanged.
                # A rotated session ID is the externally observable takeover
                # commit, so it may only be written after the GUI thread has
                # retained this exact authenticated helper session.
                return _KillSwitchStartupRecoveryOutcome(
                    session=session,
                    status=second_status,
                    decision=decision,
                )
            except Exception as exc:
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                raise _KillSwitchJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                ) from exc

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _KillSwitchStartupRecoveryOutcome)
            decision = outcome.decision
            self._connection_busy = False

            if not outcome.session.is_open:
                self._set_cached_kill_switch_status(
                    outcome.status,
                    error=(
                        "The authenticated helper session ended before startup "
                        "reconciliation could be committed."
                    ),
                )
                self.log(
                    "error",
                    "log.kill_switch.startup_recovery.failed",
                    details=(
                        "CrashRecoveryStateError: The authenticated helper "
                        "session was not open at the takeover commit boundary."
                    ),
                )
                self._update_controls()
                self.update_connection_status(force=True)
                self._show_startup_recovery_failure(
                    details=(
                        "The authenticated helper session ended before the "
                        "crash-surviving protection state could be adopted."
                    )
                )
                return

            if self._kill_switch_session is not outcome.session:
                self._close_kill_switch_session()
            # Retain the exact authenticated broker first.  Only after this
            # assignment may the recovery record be cleared or rotated.  This
            # makes a changed session ID proof that the live GUI owns a retained
            # helper session, rather than merely proof that a background worker
            # once opened one.
            self._kill_switch_session = outcome.session

            try:
                # Prove that the exact session object still transports a
                # read-only request after the worker-to-GUI handoff.  Merely
                # retaining a ready frame is not enough: pkexec or the broker
                # may have exited between the worker result and this commit.
                retained_status = outcome.session.status()
                if retained_status != outcome.status:
                    raise CrashRecoveryStateError(
                        "The host protection state changed during the retained-session handoff."
                    )
                self._set_cached_kill_switch_status(retained_status)

                if decision.disposition == CrashRecoveryDisposition.CLEAR_STALE_RECORD:
                    self._crash_recovery_journal.clear()
                elif decision.disposition == CrashRecoveryDisposition.ADOPT_CONNECTED:
                    assert decision.route_plan is not None
                    self._crash_recovery_journal.save_connected(
                        profile_uuid=decision.profile_uuid,
                        route_plan=decision.route_plan,
                    )
                elif decision.disposition == CrashRecoveryDisposition.ADOPT_BLOCKING:
                    assert decision.route_plan is not None
                    self._crash_recovery_journal.save_blocking(
                        profile_uuid=decision.profile_uuid,
                        route_plan=decision.route_plan,
                    )
            except Exception as exc:
                self._set_cached_kill_switch_status(
                    outcome.status,
                    error=f"{type(exc).__name__}: {exc}",
                )
                self.log(
                    "error",
                    "log.kill_switch.startup_recovery.failed",
                    details=f"{type(exc).__name__}: {exc}",
                )
                self._update_controls()
                self.update_connection_status(force=True)
                self._show_startup_recovery_failure(
                    details=f"{type(exc).__name__}: {exc}"
                )
                return

            if decision.disposition in {
                CrashRecoveryDisposition.NO_RECOVERY,
                CrashRecoveryDisposition.CLEAR_STALE_RECORD,
            }:
                self._set_kill_switch_reconciliation_marker(False)
                self._kill_switch_probe_baseline = None
                self._kill_switch_route_plan = None
                self.settings.remove("connection/profile_uuid")
                self.settings.sync()
                self._last_connected_state = False
                self.log(
                    "ok",
                    "log.kill_switch.startup_recovery.stale_cleared"
                    if decision.disposition == CrashRecoveryDisposition.CLEAR_STALE_RECORD
                    else "log.kill_switch.startup_recovery.clean",
                )
            elif decision.adopted:
                assert decision.route_plan is not None
                assert decision.probe_baseline is not None
                self._set_kill_switch_reconciliation_marker(True)
                self.kill_switch_runtime.set_feature_enabled(True)
                self.kill_switch_action.setChecked(True)
                self._kill_switch_probe_baseline = decision.probe_baseline
                self._kill_switch_route_plan = decision.route_plan
                self.settings.setValue("connection/profile_uuid", decision.profile_uuid)
                self.settings.sync()
                connected = (
                    decision.disposition == CrashRecoveryDisposition.ADOPT_CONNECTED
                )
                self._last_connected_state = connected
                self.log(
                    "ok" if connected else "warning",
                    "log.kill_switch.startup_recovery.adopted_connected"
                    if connected
                    else "log.kill_switch.startup_recovery.adopted_blocking",
                )
            else:
                if outcome.status.present:
                    self.kill_switch_runtime.set_feature_enabled(True)
                    self.kill_switch_action.setChecked(True)
                self._set_cached_kill_switch_status(
                    outcome.status,
                    error=decision.reason,
                )
                self.log(
                    "error",
                    "log.kill_switch.startup_recovery.refused",
                    details=decision.reason,
                )

            self._update_controls()
            self.update_connection_status(force=True)
            self._release_initial_region_refresh_if_safe()
            if (
                decision.adopted
                and self._last_connected_state is True
            ):
                self.refresh_public_info(show_errors=False)
            elif (
                not decision.adopted
                and decision.disposition not in {
                    CrashRecoveryDisposition.NO_RECOVERY,
                    CrashRecoveryDisposition.CLEAR_STALE_RECORD,
                }
            ):
                self._show_startup_recovery_failure(details=decision.reason)

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            cause = error
            if isinstance(error, _KillSwitchJobFailure):
                cause = error.cause
                if error.session is not None and error.session.is_open:
                    if self._kill_switch_session is not error.session:
                        self._close_kill_switch_session()
                    self._kill_switch_session = error.session
                self._set_cached_kill_switch_status(
                    error.status,
                    error=error.status_error or str(cause),
                )
            else:
                self._set_cached_kill_switch_status(
                    self._kill_switch_status,
                    error=str(error),
                )
            self.log(
                "error",
                "log.kill_switch.startup_recovery.failed",
                details=f"{type(cause).__name__}: {cause}",
            )
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_startup_recovery_failure(
                details=f"{type(cause).__name__}: {cause}"
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def _recheck_kill_switch_status(
        self,
        *,
        after_absent: Callable[[], None] | None = None,
        announce_absent: bool = True,
    ) -> None:
        """Reconcile stale GUI state after a documented external reset.

        This is deliberately read-only: it asks the fixed installed helper for
        the current production-table status and never enables, disables, or
        removes firewall rules. A verified absent table clears only stale
        in-memory recovery data from this GUI process.
        """

        if self._stage4_preview or self._connection_busy:
            return
        try:
            connected = network_manager.is_connected()
        except Exception as exc:
            self._show_error(exc)
            return
        if connected:
            self._show_error(
                AppError(
                    "error.kill_switch_status_recheck.title",
                    "error.kill_switch_status_recheck.connected_message",
                    details=(
                        "Read-only emergency-reset reconciliation is allowed only "
                        "while the PIA WireGuard profile is disconnected."
                    ),
                )
            )
            return

        self._connection_busy = True
        self._update_controls()
        self.log("info", "log.kill_switch.status_recheck.started")

        def job() -> _KillSwitchStatusRecheckOutcome:
            status = KillSwitchClient(timeout=120.0).status()
            return _KillSwitchStatusRecheckOutcome(status=status)

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _KillSwitchStatusRecheckOutcome)
            self._connection_busy = False
            self._set_cached_kill_switch_status(outcome.status)
            if outcome.status.present:
                self.log("warning", "log.kill_switch.status_recheck.present")
                self._update_controls()
                self.update_connection_status(force=True)
                if after_absent is not None:
                    error = AppError(
                        "error.kill_switch_quit_blocked.title",
                        "error.kill_switch_quit_blocked.message",
                        details=(
                            "The read-only helper status check verified that the "
                            "production firewall table is still active."
                        ),
                    )
                else:
                    error = AppError(
                        "error.kill_switch_status_recheck.title",
                        "error.kill_switch_status_recheck.present_message",
                        details=(
                            "The fixed installed helper verified a present and "
                            "structurally valid production firewall table."
                        ),
                    )
                self._show_error(error)
                return

            self._kill_switch_probe_baseline = None
            self._kill_switch_route_plan = None
            self.settings.remove("connection/profile_uuid")
            self.settings.sync()
            self._close_kill_switch_session()
            self._clear_crash_recovery_record_after_safe_release()
            self.log("ok", "log.kill_switch.status_recheck.absent")
            self._last_connected_state = False
            self._update_controls()
            self.update_connection_status(force=True)
            self._release_initial_region_refresh_if_safe()
            if after_absent is not None:
                after_absent()
                return
            self.public_info = None
            if announce_absent:
                QMessageBox.information(
                    self,
                    tr("kill_switch.status_recheck.absent_title"),
                    tr("kill_switch.status_recheck.absent_message"),
                )

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self._set_cached_kill_switch_status(
                self._kill_switch_status,
                error=str(error),
            )
            self.log("error", "log.kill_switch.status_recheck.failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(
                AppError(
                    "error.kill_switch_status_recheck.title",
                    "error.kill_switch_status_recheck.message",
                    details=f"{type(error).__name__}: {error}",
                )
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def emergency_reset(self) -> None:
        """Deliberately restore normal networking in VPN-first fail-closed order."""

        if self._stage4_preview or self._connection_busy:
            return

        answer = QMessageBox.warning(
            self,
            tr("emergency_reset.confirm_title"),
            tr("emergency_reset.confirm_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._connection_busy = True
        self._update_controls()
        self.log("warning", "log.kill_switch.emergency_reset.started")

        def job() -> EmergencyResetResult:
            return run_verified_emergency_reset(
                client=KillSwitchClient(timeout=120.0),
                vpn_backend=network_manager,
                recovery_store=self._crash_recovery_journal.store,
            )

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, EmergencyResetResult)
            self._connection_busy = False
            self._close_kill_switch_session()
            self._set_cached_kill_switch_status(outcome.firewall_status)
            self._kill_switch_probe_baseline = None
            self._kill_switch_route_plan = None
            self._set_kill_switch_reconciliation_marker(False)
            self.settings.remove("connection/profile_uuid")
            self.settings.sync()
            self._last_connected_state = False
            self.public_info = None
            self.log("ok", "log.kill_switch.emergency_reset.completed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._release_initial_region_refresh_if_safe()
            QMessageBox.information(
                self,
                tr("emergency_reset.complete_title"),
                tr("emergency_reset.complete_message"),
            )

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self._set_cached_kill_switch_status(
                self._kill_switch_status,
                error=str(error),
            )
            self.log(
                "error",
                "log.kill_switch.emergency_reset.failed",
                details=f"{type(error).__name__}: {error}",
            )
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(
                AppError(
                    "emergency_reset.failed_title",
                    "emergency_reset.failed_message",
                    details=f"{type(error).__name__}: {error}",
                )
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def _startup_ipv6_guard_reconciliation_required(self) -> bool:
        if self.kill_switch_runtime.feature_enabled:
            return False
        if self._ipv6_guard_expected():
            return True
        try:
            return network_manager.is_connected()
        except Exception:
            return False

    def _cancel_ipv6_guard_startup_after_helper_gate(
        self, audit: HelperInstallationAudit
    ) -> None:
        self._set_cached_ipv6_guard_status(None, error=audit.details)
        # If an ordinary PIA VPN is active but this AppImage cannot verify the
        # exact helper/guard boundary, stop the VPN rather than present a
        # connected state that might leak native IPv6.  Any existing guard table
        # is left untouched because it cannot be verified safely here.
        try:
            connected = network_manager.is_connected()
        except Exception:
            connected = None
        if connected is True:
            try:
                network_manager.disconnect(
                    str(self.settings.value("connection/profile_uuid", "")).strip()
                )
            except Exception as exc:
                self._show_error(
                    AppError(
                        "error.ipv6_guard_startup.title",
                        "error.ipv6_guard_startup.message",
                        details=f"Helper gate: {audit.details}; VPN stop failed: {exc}",
                    )
                )
                return
            self._last_connected_state = False
            self.settings.remove("connection/profile_uuid")
            self.settings.sync()
        self._update_controls()
        self.update_connection_status(force=True)

    def _reconcile_ipv6_guard_startup(self, *, _helper_checked: bool = False) -> None:
        if self._stage4_preview or self.kill_switch_runtime.feature_enabled:
            return
        if self._connection_busy:
            QTimer.singleShot(250, self._reconcile_ipv6_guard_startup)
            return
        if not self._startup_ipv6_guard_reconciliation_required():
            return
        if not _helper_checked:
            self._ensure_packaged_kill_switch_helper(
                on_ready=lambda: self._reconcile_ipv6_guard_startup(_helper_checked=True),
                on_cancel=self._cancel_ipv6_guard_startup_after_helper_gate,
            )
            return

        self._connection_busy = True
        self._update_controls()
        self.log("info", "log.ipv6_guard.startup_check")
        existing_session = self._ipv6_guard_session

        def job() -> _NormalGuardStartupOutcome:
            session = existing_session or KillSwitchSessionClient(timeout=120.0)
            try:
                result = IPv6GuardLifecycle(
                    session=session,
                    vpn_backend=network_manager,
                ).reconcile_startup()
                return _NormalGuardStartupOutcome(session=session, result=result)
            except Exception as exc:
                status: IPv6GuardStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.ipv6_guard_status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                cause = exc.cause if isinstance(exc, IPv6GuardStartupError) and exc.cause else exc
                raise _IPv6GuardJobFailure(
                    cause,
                    session=session,
                    status=status,
                    status_error=status_error,
                    guard_retained=True,
                    vpn_connected=(exc.vpn_connected if isinstance(exc, IPv6GuardStartupError) else None),
                ) from exc

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _NormalGuardStartupOutcome)
            self._connection_busy = False
            disposition = outcome.result.disposition
            self._set_cached_ipv6_guard_status(outcome.result.guard_status)
            if disposition == "adopted-connected":
                if self._ipv6_guard_session is not outcome.session:
                    self._close_ipv6_guard_session()
                self._ipv6_guard_session = outcome.session
                self._set_ipv6_guard_expected(True)
                self._last_connected_state = True
                self.log("ok", "log.ipv6_guard.startup_adopted")
                self.refresh_public_info(show_errors=False)
            else:
                self._set_ipv6_guard_expected(False)
                self._last_connected_state = False
                self.settings.remove("connection/profile_uuid")
                self.settings.sync()
                try:
                    outcome.session.close()
                except Exception:
                    pass
                self._close_ipv6_guard_session()
                if disposition == "cleared-stale-guard":
                    self.log("ok", "log.ipv6_guard.startup_stale_cleared")
                elif disposition == "stopped-unprotected-vpn":
                    self.log("warning", "log.ipv6_guard.startup_unprotected_stopped")
                    self._show_error(
                        AppError(
                            "error.ipv6_guard_startup.title",
                            "error.ipv6_guard_startup.unprotected_message",
                        )
                    )
                else:
                    self.log("ok", "log.ipv6_guard.startup_clean")
            self._update_controls()
            self.update_connection_status(force=True)

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            cause = error
            if isinstance(error, _IPv6GuardJobFailure):
                cause = error.cause
                self._set_cached_ipv6_guard_status(
                    error.status,
                    error=error.status_error or str(cause),
                )
                self._set_ipv6_guard_expected(True)
                if error.session is not None:
                    if self._ipv6_guard_session is not error.session:
                        self._close_ipv6_guard_session()
                    self._ipv6_guard_session = error.session
                if error.vpn_connected is not None:
                    self._last_connected_state = error.vpn_connected

            # Startup must never leave a normal PIA VPN running when the small
            # IPv6 guard could not be verified.  Disconnecting the VPN is the
            # only safe unprivileged mutation here; any unknown firewall table
            # is deliberately retained for later explicit reconciliation.
            guard_verified = bool(
                self._ipv6_guard_status is not None
                and self._ipv6_guard_status.protection_active
                and not self._ipv6_guard_status_error
            )
            safety_note = ""
            if not guard_verified:
                try:
                    connected_now = network_manager.is_connected()
                except Exception as state_exc:
                    safety_note = f"; VPN state also became unknown: {state_exc}"
                else:
                    if connected_now:
                        try:
                            network_manager.disconnect(
                                str(self.settings.value("connection/profile_uuid", "")).strip()
                            )
                        except Exception as stop_exc:
                            safety_note = f"; unsafe VPN stop failed: {stop_exc}"
                        else:
                            self._last_connected_state = False
                            self.settings.remove("connection/profile_uuid")
                            self.settings.sync()
                            safety_note = "; unverified normal VPN was stopped"

            self.log("error", "log.ipv6_guard.startup_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(
                AppError(
                    "error.ipv6_guard_startup.title",
                    "error.ipv6_guard_startup.message",
                    details=f"{type(cause).__name__}: {cause}{safety_note}",
                )
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def _log_connection_events(
        self,
        events: tuple[ConnectionEvent, ...] | list[ConnectionEvent],
    ) -> None:
        for event in events:
            key = _CONNECTION_EVENT_LOG_KEYS.get(event.phase)
            if key is not None:
                self.log(event.level, key)

    def _log_recovery_events(
        self,
        events: tuple[RecoveryEvent, ...] | list[RecoveryEvent],
    ) -> None:
        for event in events:
            key = _RECOVERY_EVENT_LOG_KEYS.get(event.phase)
            if key is not None:
                self.log(event.level, key)

    def _close_kill_switch_session(self) -> None:
        session = self._kill_switch_session
        self._kill_switch_session = None
        if session is None:
            return
        try:
            session.close()
        except Exception:
            # Closing the restricted broker never changes the firewall table.
            pass

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
            self.kill_switch_action,
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

        self.kill_switch_action.setText(tr("menu.kill_switch"))
        self.kill_switch_action.setToolTip(tr("menu.kill_switch_tooltip"))
        self.credentials_action.setText(tr("menu.credentials"))
        self.live_log_action.setText(tr("menu.live_log"))
        self.tray_action.setText(tr("menu.tray"))

        self.help_menu.setTitle(tr("menu.help"))
        self.emergency_reset_action.setText(tr("menu.emergency_reset"))
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

        self.kill_switch_action.setChecked(
            self.kill_switch_runtime.feature_enabled
        )

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
                action.setText(tr(state.title_key).replace("&", "&&"))
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

    def change_kill_switch_enabled(self, enabled: bool) -> None:
        if self._stage4_preview:
            self.kill_switch_action.setChecked(
                self.kill_switch_runtime.feature_enabled
            )
            return
        current = self.kill_switch_runtime.feature_enabled
        if bool(enabled) == current:
            return
        if self._connection_busy:
            self.kill_switch_action.setChecked(current)
            return

        try:
            connected = network_manager.is_connected()
        except Exception as exc:
            self.kill_switch_action.setChecked(current)
            self._show_error(exc)
            return
        if connected:
            self.kill_switch_action.setChecked(current)
            QMessageBox.warning(
                self,
                tr("kill_switch.preference.connected_title"),
                tr("kill_switch.preference.connected_message"),
            )
            return

        if enabled:
            self._authorize_kill_switch_preference()
        else:
            self._disable_kill_switch_preference()

    def _ensure_packaged_kill_switch_helper(
        self,
        *,
        on_ready: Callable[[], None],
        on_cancel: Callable[[HelperInstallationAudit], None],
    ) -> None:
        """Gate privileged VPN protection on an exact root-owned helper match.

        The same restricted helper owns the normal-mode IPv6-only guard and the
        optional full Session Kill Switch.  Source-tree runs remain unmanaged.
        A packaged AppImage never treats a merely protocol-compatible old helper
        as current: the complete installed boundary must match this AppImage.
        """

        audit = self._packaged_helper_manager.audit()
        if audit.current:
            on_ready()
            return

        if not audit.installable:
            self.log(
                "error",
                "log.kill_switch.helper_install.blocked",
                details=audit.details,
            )
            self._show_error(
                AppError(
                    "error.kill_switch_helper_install.title",
                    "error.kill_switch_helper_install.unsafe_message"
                    if audit.state is HelperInstallationState.UNSAFE
                    else "error.kill_switch_helper_install.bundle_message",
                    details=audit.details,
                )
            )
            on_cancel(audit)
            return

        updating = audit.state is HelperInstallationState.OUTDATED
        answer = QMessageBox.question(
            self,
            tr(
                "kill_switch.helper_install.update_title"
                if updating
                else "kill_switch.helper_install.install_title"
            ),
            tr(
                "kill_switch.helper_install.update_message"
                if updating
                else "kill_switch.helper_install.install_message"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log("warning", "log.kill_switch.helper_install.declined")
            on_cancel(audit)
            return

        self._connection_busy = True
        self._update_controls()
        self.log(
            "info",
            "log.kill_switch.helper_install.updating"
            if updating
            else "log.kill_switch.helper_install.installing",
        )

        def job() -> HelperInstallationAudit:
            return self._packaged_helper_manager.install_or_upgrade()

        def success(result: Any) -> None:
            installed = result
            assert isinstance(installed, HelperInstallationAudit)
            self._connection_busy = False
            self.log("ok", "log.kill_switch.helper_install.ready")
            self._update_controls()
            on_ready()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            failed_audit = self._packaged_helper_manager.audit()
            self.log(
                "error",
                "log.kill_switch.helper_install.failed",
                details=f"{type(error).__name__}: {error}",
            )
            self._update_controls()
            self._show_error(
                AppError(
                    "error.kill_switch_helper_install.title",
                    "error.kill_switch_helper_install.message",
                    details=f"{type(error).__name__}: {error}",
                )
            )
            on_cancel(failed_audit)

        self._run_worker(job, on_success=success, on_failure=failure)

    def _cancel_kill_switch_enable_after_helper_gate(
        self, audit: HelperInstallationAudit
    ) -> None:
        self.kill_switch_runtime.set_feature_enabled(False)
        self.kill_switch_action.setChecked(False)
        self._set_cached_kill_switch_status(None, error=audit.details)
        self._update_controls()
        self.update_connection_status(force=True)

    def _mark_packaged_helper_unavailable_for_startup(
        self, audit: HelperInstallationAudit
    ) -> None:
        # Keep the persisted preference intact.  A user who cancels an upgrade
        # gets a visible fail-closed state and can authorize it on the next check.
        self._set_cached_kill_switch_status(None, error=audit.details)
        self.log(
            "warning",
            "log.kill_switch.helper_install.startup_not_ready",
            details=audit.details,
        )
        self._update_controls()
        self.update_connection_status(force=True)

    def _authorize_kill_switch_preference(self, *, _helper_checked: bool = False) -> None:
        if not _helper_checked:
            self._ensure_packaged_kill_switch_helper(
                on_ready=lambda: self._authorize_kill_switch_preference(_helper_checked=True),
                on_cancel=self._cancel_kill_switch_enable_after_helper_gate,
            )
            return

        self._connection_busy = True
        self._update_controls()
        self.kill_switch_action.setEnabled(False)
        self.log("info", "log.kill_switch.preference.enabling")

        def job() -> _KillSwitchAuthorizationOutcome:
            session = KillSwitchSessionClient(timeout=120.0)
            try:
                session.open()
                status = session.status()
                if status.present or status.state != "disabled":
                    raise AppError(
                        "error.kill_switch_existing_lock.title",
                        "error.kill_switch_existing_lock.message",
                        details=(
                            "A verified production kill-switch table already exists, "
                            "but this app session has no matching probe baseline."
                        ),
                    )

                # A crash-surviving normal-mode IPv6 guard is a separate
                # firewall mode.  The preference toggle is allowed only while
                # the VPN is down, so verify that invariant again inside the
                # worker before changing either protection mode.
                if network_manager.is_connected():
                    raise IPv6GuardLifecycleError(
                        "Refusing to enable the Session Kill Switch preference while the PIA VPN is active."
                    )
                guard = session.ipv6_guard_status()
                if guard.present:
                    if not guard.protection_active:
                        raise IPv6GuardLifecycleError(
                            "The existing IPv6-only guard could not be structurally verified."
                        )
                    guard = session.ipv6_guard_disable()
                    if (
                        guard.state != "disabled"
                        or guard.present
                        or not guard.verified
                        or guard.problems
                    ):
                        raise IPv6GuardLifecycleError(
                            "The IPv6-only guard could not be verified as released before enabling the Kill Switch."
                        )
                return _KillSwitchAuthorizationOutcome(
                    session=session,
                    status=status,
                )
            except Exception as exc:
                status: KillSwitchStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                raise _KillSwitchJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                ) from exc

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _KillSwitchAuthorizationOutcome)
            self._kill_switch_session = outcome.session
            self._set_cached_kill_switch_status(outcome.status)
            self._set_ipv6_guard_expected(False)
            self._set_cached_ipv6_guard_status(None)
            self._close_ipv6_guard_session()
            self._set_kill_switch_reconciliation_marker(False)
            self.kill_switch_runtime.set_feature_enabled(True)
            self._connection_busy = False
            self.kill_switch_action.setChecked(True)
            self.kill_switch_action.setEnabled(True)
            self.log("ok", "log.kill_switch.preference.enabled")
            self._update_controls()
            self.update_connection_status(force=True)

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self.kill_switch_action.setEnabled(True)
            if isinstance(error, _KillSwitchJobFailure):
                if error.status is not None and error.status.present:
                    self._kill_switch_session = error.session
                    self._set_cached_kill_switch_status(
                        error.status,
                        error=error.status_error,
                    )
                    self.kill_switch_runtime.set_feature_enabled(True)
                    self.kill_switch_action.setChecked(True)
                else:
                    if error.session is not None:
                        try:
                            error.session.close()
                        except Exception:
                            pass
                    self._set_cached_kill_switch_status(None)
                    self.kill_switch_runtime.set_feature_enabled(False)
                    self.kill_switch_action.setChecked(False)
                cause = error.cause
            else:
                cause = error
                self.kill_switch_runtime.set_feature_enabled(False)
                self.kill_switch_action.setChecked(False)
            authorization_cancelled = self._authorization_denied_in_chain(cause)
            self.log(
                "warning" if authorization_cancelled else "error",
                "log.kill_switch.preference.authorization_cancelled"
                if authorization_cancelled
                else "log.kill_switch.preference.failed",
            )
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_kill_switch_error(
                cause,
                authorization_cancel_safe=True,
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def _disable_kill_switch_preference(self) -> None:
        self._connection_busy = True
        self._update_controls()
        self.kill_switch_action.setEnabled(False)
        self.log("info", "log.kill_switch.preference.disabling")

        baseline = self._kill_switch_probe_baseline
        existing_session = self._kill_switch_session
        profile_uuid = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()

        def job() -> _ProtectedDisconnectOutcome:
            session = existing_session or KillSwitchSessionClient(timeout=120.0)
            events: list[ConnectionEvent] = []
            try:
                if existing_session is not None:
                    try:
                        session.open()
                        status = session.status()
                    except Exception:
                        try:
                            session.close()
                        except Exception:
                            pass
                        session = KillSwitchSessionClient(timeout=120.0)
                        session.open()
                        status = session.status()
                else:
                    session.open()
                    status = session.status()
                if status.present:
                    if baseline is None:
                        raise AppError(
                            "error.kill_switch_existing_lock.title",
                            "error.kill_switch_existing_lock.message",
                            details=(
                                "The firewall is active, but the current app session "
                                "has no pre-connection probe baseline."
                            ),
                        )
                    orchestrator = KillSwitchConnectionOrchestrator(
                        session=session,
                        vpn_backend=network_manager,
                        event_sink=events.append,
                    )
                    result = orchestrator.disconnect_intentionally(
                        profile_uuid=profile_uuid,
                        kill_switch_enabled=True,
                        blocked_path_probe=baseline.ordinary_path_is_blocked,
                    )
                    if result.firewall_status is None:
                        raise RuntimeError(
                            "Protected release returned no verified helper status."
                        )
                    status = result.firewall_status
                return _ProtectedDisconnectOutcome(
                    session=session,
                    status=status,
                    events=tuple(events),
                )
            except Exception as exc:
                status: KillSwitchStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                raise _KillSwitchJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                    baseline=baseline,
                    events=tuple(events),
                ) from exc

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _ProtectedDisconnectOutcome)
            self._log_connection_events(outcome.events)
            self._kill_switch_session = outcome.session
            self._set_cached_kill_switch_status(outcome.status)
            self.kill_switch_runtime.set_feature_enabled(False)
            self._kill_switch_probe_baseline = None
            self._kill_switch_route_plan = None
            self._connection_busy = False
            self.kill_switch_action.setChecked(False)
            self.kill_switch_action.setEnabled(True)
            self.log("ok", "log.kill_switch.preference.disabled")
            self._close_kill_switch_session()
            self._clear_crash_recovery_record_after_safe_release()
            self._update_controls()
            self.update_connection_status(force=True)
            self.public_info = None

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self.kill_switch_action.setEnabled(True)
            self.kill_switch_action.setChecked(True)
            self.kill_switch_runtime.set_feature_enabled(True)
            if isinstance(error, _KillSwitchJobFailure):
                self._log_connection_events(error.events)
                self._kill_switch_probe_baseline = error.baseline
                if error.status is not None:
                    self._kill_switch_session = error.session
                else:
                    if error.session is not None:
                        try:
                            error.session.close()
                        except Exception:
                            pass
                    self._kill_switch_session = None
                self._set_cached_kill_switch_status(
                    error.status,
                    error=error.status_error,
                )
                cause = error.cause
            else:
                cause = error
                self._set_cached_kill_switch_status(
                    self._kill_switch_status,
                    error=str(error),
                )
            self.log("error", "log.kill_switch.preference.failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(self._friendly_kill_switch_error(cause))

        self._run_worker(job, on_success=success, on_failure=failure)

    @staticmethod
    def _friendly_kill_switch_error(error: BaseException) -> AppError:
        if isinstance(error, AppError):
            return error
        details = f"{type(error).__name__}: {error}"
        if isinstance(error, NetworkProbeError):
            return AppError(
                "error.kill_switch_probe.title",
                "error.kill_switch_probe.message",
                details=details,
            )
        if isinstance(error, ProtectedReconnectError):
            return AppError(
                "error.kill_switch_recovery.title",
                "error.kill_switch_recovery.message",
                details=details,
            )
        if isinstance(error, ProtectedServerSwitchError):
            return AppError(
                "error.kill_switch_switch_failed.title",
                "error.kill_switch_switch_failed.message",
                details=details,
            )
        if isinstance(error, KillSwitchPreparationError):
            return AppError(
                "error.kill_switch_prepare.title",
                "error.kill_switch_prepare.message",
                details=details,
            )
        if isinstance(error, (VpnStartError, PostConnectVerificationError)):
            retained = bool(getattr(error, "firewall_retained", False))
            return AppError(
                "error.kill_switch_blocking.title"
                if retained
                else "error.kill_switch_connection.title",
                "error.kill_switch_blocking.message"
                if retained
                else "error.kill_switch_connection.message",
                details=details,
            )
        if isinstance(error, IntentionalDisconnectError):
            return AppError(
                "error.kill_switch_blocking.title",
                "error.kill_switch_blocking.message",
                details=details,
            )
        if isinstance(error, IPv6GuardLifecycleError):
            return AppError(
                "error.ipv6_guard.title",
                "error.ipv6_guard.retained_message",
                details=details,
            )
        if isinstance(error, KillSwitchClientError):
            return AppError(
                "error.kill_switch_authorization.title",
                "error.kill_switch_authorization.message",
                details=details,
            )
        return AppError(
            "error.kill_switch_connection.title",
            "error.kill_switch_connection.message",
            details=details,
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _scroll_live_log_to_end(self) -> None:
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log(self, level: str, key: str, **values: Any) -> None:
        scrollbar = self.log_view.verticalScrollBar()
        follow_tail = (
            not self.log_view.isVisible()
            or scrollbar.value() >= max(0, scrollbar.maximum() - 2)
        )
        message = redact_secrets(tr(key, **values))
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_key = f"log.level.{level}"
        level_text = tr(level_key)
        self.log_view.appendPlainText(
            f"{timestamp}  {level_text:<7}  {message}"
        )
        if follow_tail:
            self._scroll_live_log_to_end()

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def save_log(self) -> None:
        default_path = state_dir() / "pia-bazzite.log"
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("log.save_title"),
            str(default_path),
            tr("log.file_filter"),
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
    def _request_initial_region_refresh(self) -> None:
        """Start the first network refresh only when startup protection permits it.

        A crash-surviving full Kill Switch can intentionally block every normal
        network path while startup reconciliation waits for Polkit.  Starting a
        server-list request in parallel would therefore produce an expected
        network failure and, worse, a modal error dialog can obscure the Polkit
        authentication prompt.  Keep the cached region list and defer the first
        network request until the host state is verified as connected or safely
        released.
        """

        if self._startup_kill_switch_reconciliation_required():
            self._initial_region_refresh_pending = True
            return
        QTimer.singleShot(0, self.refresh_regions)

    def _release_initial_region_refresh_if_safe(self) -> None:
        if not self._initial_region_refresh_pending:
            return
        try:
            connected = network_manager.is_connected()
        except Exception:
            return
        if self._disconnected_kill_switch_may_block(connected=connected):
            return
        self._initial_region_refresh_pending = False
        QTimer.singleShot(0, self.refresh_regions)

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

        # The first server-list refresh starts only after the first-run modal
        # flow has finished *and* any crash-surviving full Kill Switch has been
        # reconciled. Qt timers keep running inside dialog.exec(), and a safely
        # blocked recovery state has no normal network path by design.
        self._request_initial_region_refresh()

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

    @staticmethod
    def _authorization_denied_in_chain(error: BaseException) -> bool:
        """Return True only when Polkit cancellation/denial is in the exception chain."""

        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, AuthorizationDeniedError):
                return True
            next_error = current.__cause__
            if next_error is None:
                next_error = current.__context__
            current = next_error
        return False

    def _show_authorization_not_granted(self, error: BaseException) -> None:
        """Present a deliberate Polkit cancellation as a neutral user outcome."""

        details = redact_secrets(f"{type(error).__name__}: {error}")
        self.log("warning", "log.technical_details", details=details)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("authorization.not_granted.title"))
        box.setText(tr("authorization.not_granted.message"))
        box.setInformativeText(tr("common.details_hint"))
        box.setDetailedText(details)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _show_kill_switch_error(
        self,
        error: BaseException,
        *,
        authorization_cancel_safe: bool = False,
    ) -> None:
        if authorization_cancel_safe and self._authorization_denied_in_chain(error):
            self._show_authorization_not_granted(error)
            return
        self._show_error(self._friendly_kill_switch_error(error))

    def _show_startup_recovery_failure(self, *, details: str) -> None:
        """Offer explicit safe recovery choices after a failed startup reconciliation."""

        safe_details = redact_secrets(details)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(tr("error.kill_switch_startup_recovery.title"))
        box.setText(tr("error.kill_switch_startup_recovery.message"))
        if safe_details:
            box.setInformativeText(tr("common.details_hint"))
            box.setDetailedText(safe_details)

        retry_button = box.addButton(
            tr("startup_recovery.retry"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        reset_button = box.addButton(
            tr("menu.emergency_reset"),
            QMessageBox.ButtonRole.ActionRole,
        )
        cancel_button = box.addButton(
            tr("common.cancel"),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(retry_button)
        box.setEscapeButton(cancel_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked is retry_button:
            QTimer.singleShot(0, self._reconcile_kill_switch_startup)
        elif clicked is reset_button:
            # The reset remains deliberate: this only opens its independent
            # confirmation dialog; it is never executed automatically.
            QTimer.singleShot(0, self.emergency_reset)

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
            self.region_favorites.refresh_snapshots(self.regions)
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

    def _favorite_snapshot_matches_query(
        self,
        favorite: FavoriteRegion,
        query: str,
    ) -> bool:
        if not query:
            return True
        return query in f"{favorite.region_id} {favorite.name}".casefold()

    def _favorite_snapshot_display_name(self, favorite: FavoriteRegion) -> str:
        name = favorite.name
        if favorite.geo:
            geo_text = "virtueller Standort" if language() == "de" else "virtual location"
            name = f"{name} ({geo_text})"
        return name

    def _region_marker_icon(self, symbol: str, *, accent: bool) -> QIcon:
        size = self.region_combo.iconSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        color = (
            QColor(REGION_MARKER_ACCENT_COLOR)
            if accent
            else self.region_combo.palette().color(QPalette.ColorRole.Text)
        )

        if symbol == "⚡":
            # Do not rely on the current UI font containing the Unicode
            # lightning glyph.  Some Linux/Qt font stacks render it as an
            # emoji/fallback glyph in QAction text but not when QPainter draws
            # into a QPixmap, which can leave the combo marker blank.
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
            font = QFont(self.region_combo.font())
            font.setBold(symbol == "★")
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

    def _add_region_combo_item(
        self,
        *,
        text: str,
        region_id: str,
        favorite: bool,
        available: bool,
    ) -> None:
        star = "★" if favorite else "☆"
        icon = self._region_marker_icon(star, accent=favorite)
        self.region_combo.addItem(icon, text, region_id)
        row = self.region_combo.count() - 1
        self.region_combo.setItemData(row, True, REGION_FAVORITE_TOGGLE_ROLE)
        self.region_combo.set_region_row_available(row, available)
        if available:
            tooltip_key = (
                "favorites.remove_tooltip"
                if favorite
                else "favorites.add_tooltip"
            )
            tooltip = tr(tooltip_key)
        else:
            tooltip = tr("favorites.unavailable_tooltip")
        self.region_combo.setItemData(
            row,
            tooltip,
            Qt.ItemDataRole.ToolTipRole,
        )

    def _first_selectable_region_index(self) -> int:
        for row in range(self.region_combo.count()):
            available = self.region_combo.itemData(
                row,
                REGION_FAVORITE_AVAILABLE_ROLE,
            )
            if available is False:
                continue
            return row
        return -1

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
        favorite_ids = {
            favorite.region_id for favorite in self.region_favorites.all()
        }
        favorite_regions = [
            region for region in filtered if region.region_id in favorite_ids
        ]
        normal_regions = [
            region for region in filtered if region.region_id not in favorite_ids
        ]
        current_ids = {region.region_id for region in self.regions}
        missing_favorites = [
            favorite
            for favorite in self.region_favorites.all()
            if favorite.region_id not in current_ids
            and self._favorite_snapshot_matches_query(favorite, query)
        ]

        self.region_combo.blockSignals(True)
        self.region_combo.clear()

        for region in favorite_regions:
            self._add_region_combo_item(
                text=region_display_name(region, language()),
                region_id=region.region_id,
                favorite=True,
                available=True,
            )

        for favorite in missing_favorites:
            unavailable = tr("favorites.unavailable_suffix")
            self._add_region_combo_item(
                text=f"{self._favorite_snapshot_display_name(favorite)} · {unavailable}",
                region_id=favorite.region_id,
                favorite=True,
                available=False,
            )

        if not query:
            fastest_text = tr("connection.fastest")
            if self.regions and self.regions[0].ping_ms is not None:
                fastest_text += f" · {self.regions[0].ping_ms:.0f} ms"
            fastest_icon = self._region_marker_icon("⚡", accent=True)
            self.region_combo.addItem(fastest_icon, fastest_text, FASTEST_ID)
            fastest_row = self.region_combo.count() - 1
            self.region_combo.setItemData(
                fastest_row,
                True,
                REGION_FAVORITE_AVAILABLE_ROLE,
            )

        for region in normal_regions:
            self._add_region_combo_item(
                text=region_display_name(region, language()),
                region_id=region.region_id,
                favorite=False,
                available=True,
            )

        target_index = self.region_combo.findData(selected_id)
        if target_index >= 0 and self.region_combo.itemData(
            target_index,
            REGION_FAVORITE_AVAILABLE_ROLE,
        ) is False:
            target_index = -1
        if target_index < 0:
            target_index = self._first_selectable_region_index()
        self.region_combo.setCurrentIndex(target_index)
        self.region_combo.blockSignals(False)
        self._update_controls()

    def _toggle_region_favorite(self, region_id: str) -> None:
        region_id = str(region_id).strip()
        if not region_id or region_id == FASTEST_ID:
            return

        if self.region_favorites.is_favorite(region_id):
            self.region_favorites.remove(region_id)
        else:
            region = self._region_by_id(region_id)
            if region is None:
                return
            result = self.region_favorites.add(region)
            if result == FavoriteAddResult.LIMIT_REACHED:
                QMessageBox.information(
                    self,
                    tr("favorites.limit_title"),
                    tr(
                        "favorites.limit_message",
                        limit=MAX_FAVORITE_REGIONS,
                    ),
                )
                return

        self._populate_region_combo()
        self._rebuild_tray_menu()

    def _selection_changed(self, index: int) -> None:
        if index < 0 or self._region_selection_guard:
            return
        selected_id = str(self.region_combo.itemData(index))
        self.settings.setValue("connection/selected_region_id", selected_id)
        self.settings.sync()
        self._rebuild_tray_menu()

        if self._connection_busy:
            return
        try:
            connected = network_manager.is_connected()
        except Exception:
            return
        region = self._selected_region()
        if (
            connected
            and region is not None
            and self._active_region_id
            and region.region_id != self._active_region_id
        ):
            QTimer.singleShot(0, lambda selected=region: self.connect_region(selected))

    def _restore_active_region_selection(self) -> None:
        if not self._active_region_id:
            return
        self.settings.setValue(
            "connection/selected_region_id",
            self._active_region_id,
        )
        self.settings.sync()
        index = self.region_combo.findData(self._active_region_id)
        if index < 0:
            active_region = self._region_by_id(self._active_region_id)
            if active_region is None:
                return
            self._add_region_combo_item(
                text=region_display_name(active_region, language()),
                region_id=active_region.region_id,
                favorite=self.region_favorites.is_favorite(active_region.region_id),
                available=True,
            )
            index = self.region_combo.count() - 1
        self._region_selection_guard = True
        try:
            self.region_combo.setCurrentIndex(index)
        finally:
            self._region_selection_guard = False
        self._rebuild_tray_menu()

    def _confirm_server_switch(self, region: Region) -> bool:
        current = self._region_by_id(self._active_region_id)
        current_name = (
            localized_region_name(current, language())
            if current is not None
            else self._active_region_fallback or tr("common.unknown")
        )
        target_name = localized_region_name(region, language())
        answer = QMessageBox.question(
            self,
            tr("server_switch.confirm_title"),
            tr(
                "server_switch.confirm_message",
                current=current_name,
                target=target_name,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

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
        except Exception as exc:
            self._show_error(exc)
            return
        if connected:
            self.disconnect()
        else:
            if self._disconnected_kill_switch_may_block(connected=False):
                if self._protected_reconnect_context_available():
                    self._start_protected_reconnect(automatic=False)
                else:
                    self._recheck_kill_switch_status()
                return
            region = self._selected_region()
            if region is None:
                QMessageBox.information(
                    self,
                    tr("connection.no_location_title"),
                    tr("connection.no_location_message"),
                )
                return
            self.connect_region(region)

    def connect_region(self, region: Region, *, _helper_checked: bool = False) -> None:
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

        if not _helper_checked:
            self._ensure_packaged_kill_switch_helper(
                on_ready=lambda: self.connect_region(region, _helper_checked=True),
                on_cancel=lambda _audit: self._restore_active_region_selection(),
            )
            return

        credentials = self._get_credentials()
        if credentials is None:
            return

        try:
            was_connected = network_manager.is_connected()
        except Exception as exc:
            self._show_error(exc)
            return

        kill_switch_enabled = self.kill_switch_runtime.feature_enabled
        if was_connected:
            if region.region_id == self._active_region_id:
                self._restore_active_region_selection()
                return
            if not self._confirm_server_switch(region):
                self._restore_active_region_selection()
                return
            if kill_switch_enabled:
                self._switch_protected_region(
                    region=region,
                    credentials=credentials,
                )
                return
        if kill_switch_enabled and self._disconnected_kill_switch_may_block(
            connected=was_connected,
        ):
            if (
                self._kill_switch_probe_baseline is None
                or self._kill_switch_route_plan is None
            ):
                self._show_error(
                    AppError(
                        "error.kill_switch_existing_lock.title",
                        "error.kill_switch_existing_lock.message",
                        details=(
                            "Protected reconnect requires the matching in-memory probe "
                            "baseline and exact firewall route from this app session."
                        ),
                    )
                )
            else:
                self._start_protected_reconnect(automatic=False)
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
        existing_session = self._kill_switch_session
        existing_guard_session = self._ipv6_guard_session
        guard_expected_before = self._ipv6_guard_expected()
        if kill_switch_enabled:
            # Persist fail-closed intent before any worker can arm the production
            # firewall.  If the GUI dies in the narrow window before the richer
            # crash-recovery record is written, the next process still knows it
            # must authenticate and inspect the host instead of assuming idle.
            self._set_kill_switch_reconciliation_marker(True)
        else:
            # Persist intent before the privileged guard is armed.  A crash
            # after that point must cause startup reconciliation instead of
            # silently assuming that native IPv6 is safe.
            self._set_ipv6_guard_expected(True)
            self.log("info", "log.ipv6_guard.arming")

        def job() -> _NormalGuardConnectOutcome | _ProtectedConnectOutcome:
            if not kill_switch_enabled:
                session = existing_guard_session or KillSwitchSessionClient(timeout=120.0)
                try:
                    create_wireguard_config(
                        config_path=config_path,
                        credentials=credentials,
                        region=region,
                    )
                    lifecycle = IPv6GuardLifecycle(
                        session=session,
                        vpn_backend=network_manager,
                    )
                    result = lifecycle.connect(config_path)
                    return _NormalGuardConnectOutcome(
                        profile_uuid=result.profile_uuid,
                        session=session,
                        status=result.guard_status,
                    )
                except Exception as exc:
                    status: IPv6GuardStatus | None = None
                    status_error = ""
                    guard_retained = True
                    vpn_connected: bool | None = None
                    cause: BaseException = exc
                    if isinstance(exc, IPv6GuardConnectError):
                        cause = exc.cause or exc
                        status = exc.guard_status
                        guard_retained = exc.guard_retained
                        vpn_connected = exc.vpn_connected
                        status_error = exc.cleanup_error
                    else:
                        if session.is_open:
                            try:
                                status = session.ipv6_guard_status()
                                guard_retained = bool(status.present)
                            except Exception as status_exc:
                                status_error = str(status_exc)
                                guard_retained = True
                        else:
                            # No authenticated guard session was ever opened in
                            # this attempt.  Preserve a pre-existing marker, but
                            # do not invent a new active guard after an early
                            # credential/config/auth failure.
                            guard_retained = guard_expected_before
                    raise _IPv6GuardJobFailure(
                        cause,
                        session=session,
                        status=status,
                        status_error=status_error,
                        guard_retained=guard_retained,
                        vpn_connected=vpn_connected,
                    ) from exc
                finally:
                    try:
                        config_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            events: list[ConnectionEvent] = []
            baseline: NetworkProbeBaseline | None = None
            route_plan: FirewallRoutePlan | None = None
            session = existing_session or KillSwitchSessionClient(timeout=120.0)
            try:
                baseline = NetworkProbeBaseline.capture()
                create_wireguard_config(
                    config_path=config_path,
                    credentials=credentials,
                    region=region,
                )
                endpoint = read_wireguard_endpoint(config_path)
                interface = discover_physical_interface(endpoint)
                plan = ConnectionPlan.create(
                    config_path=config_path,
                    physical_interfaces=(interface,),
                    endpoints=(endpoint,),
                )
                route_plan = FirewallRoutePlan.from_connection_plan(plan)

                if existing_session is not None:
                    try:
                        session.open()
                        session.status()
                    except Exception:
                        try:
                            session.close()
                        except Exception:
                            pass
                        session = KillSwitchSessionClient(timeout=120.0)

                orchestrator = KillSwitchConnectionOrchestrator(
                    session=session,
                    vpn_backend=network_manager,
                    event_sink=events.append,
                )
                result = orchestrator.connect(
                    plan,
                    kill_switch_enabled=True,
                    vpn_connected_before=False,
                )
                if result.firewall_status is None:
                    raise RuntimeError(
                        "Protected connection returned no verified helper status."
                    )
                self._save_connected_crash_recovery_record(
                    profile_uuid=result.profile_uuid,
                    route_plan=route_plan,
                )
                return _ProtectedConnectOutcome(
                    profile_uuid=result.profile_uuid,
                    session=session,
                    status=result.firewall_status,
                    baseline=baseline,
                    route_plan=route_plan,
                    events=tuple(events),
                )
            except Exception as exc:
                status: KillSwitchStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                try:
                    vpn_still_connected = network_manager.is_connected()
                except Exception as vpn_status_exc:
                    if not status_error:
                        status_error = (
                            "VPN state could not be verified after the failed protected "
                            f"connection: {vpn_status_exc}"
                        )
                else:
                    if vpn_still_connected and status is not None and status.present:
                        status_error = (
                            "The protected connection operation failed while NetworkManager "
                            "still reports the VPN as connected."
                        )
                raise _KillSwitchJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                    baseline=baseline,
                    route_plan=route_plan,
                    events=tuple(events),
                ) from exc
            finally:
                try:
                    config_path.unlink(missing_ok=True)
                except OSError:
                    pass

        def success(result: Any) -> None:
            self._connection_busy = False
            if isinstance(result, _ProtectedConnectOutcome):
                profile_uuid = result.profile_uuid
                self._log_connection_events(result.events)
                if self._kill_switch_session is not result.session:
                    self._close_kill_switch_session()
                self._kill_switch_session = result.session
                self._set_cached_kill_switch_status(result.status)
                self._kill_switch_probe_baseline = result.baseline
                self._kill_switch_route_plan = result.route_plan
                self._set_ipv6_guard_expected(False)
                self._set_cached_ipv6_guard_status(None)
                self._close_ipv6_guard_session()
                self.log("ok", "log.kill_switch.crash_record.connected_saved")
            else:
                assert isinstance(result, _NormalGuardConnectOutcome)
                profile_uuid = result.profile_uuid
                if self._ipv6_guard_session is not result.session:
                    self._close_ipv6_guard_session()
                self._ipv6_guard_session = result.session
                self._set_cached_ipv6_guard_status(result.status)
                self._set_ipv6_guard_expected(True)
                self._kill_switch_probe_baseline = None
                self._kill_switch_route_plan = None
                self._set_cached_kill_switch_status(None)
                self._close_kill_switch_session()
                self.log("ok", "log.ipv6_guard.armed")

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
            self._restore_active_region_selection()
            self._last_connected_state = True
            self.log("ok", "log.connected", region=region_name)
            self._update_controls()
            self.update_connection_status(force=True)
            self.refresh_public_info(show_errors=False)
            self._rebuild_tray_menu()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            cause = error
            if isinstance(error, _IPv6GuardJobFailure):
                cause = error.cause
                self._set_cached_ipv6_guard_status(
                    error.status,
                    error=error.status_error,
                )
                if error.guard_retained:
                    self._set_ipv6_guard_expected(True)
                    if error.session is not None:
                        if self._ipv6_guard_session is not error.session:
                            self._close_ipv6_guard_session()
                        self._ipv6_guard_session = error.session
                    self.log("warning", "log.ipv6_guard.retained_after_failure")
                else:
                    self._set_ipv6_guard_expected(False)
                    if error.session is not None:
                        try:
                            error.session.close()
                        except Exception:
                            pass
                    self._close_ipv6_guard_session()
                    self._set_cached_ipv6_guard_status(error.status)
                if error.vpn_connected is not None:
                    self._last_connected_state = error.vpn_connected
            elif isinstance(error, _KillSwitchJobFailure):
                cause = error.cause
                self._log_connection_events(error.events)
                self._kill_switch_probe_baseline = error.baseline
                self._kill_switch_route_plan = error.route_plan
                if error.status is not None and error.status.present:
                    if self._kill_switch_session is not error.session:
                        self._close_kill_switch_session()
                    self._kill_switch_session = error.session
                    self._set_cached_kill_switch_status(
                        error.status,
                        error=error.status_error,
                    )
                else:
                    if error.session is not None:
                        try:
                            error.session.close()
                        except Exception:
                            pass
                    self._kill_switch_session = None
                    self._set_cached_kill_switch_status(
                        error.status,
                        error=error.status_error,
                    )
            authorization_cancelled = self._authorization_denied_in_chain(cause)
            self.log(
                "warning" if authorization_cancelled else "error",
                "activity.connection_authorization_cancelled"
                if authorization_cancelled
                else "activity.connection_failed",
            )
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_kill_switch_error(
                cause,
                authorization_cancel_safe=True,
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def _schedule_protected_reconnect(self) -> None:
        if self._protected_reconnect_scheduled or self._connection_busy:
            return
        if not self.kill_switch_runtime.feature_enabled:
            return
        profile_uuid = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()
        route_plan = self._kill_switch_route_plan
        if profile_uuid and route_plan is not None:
            try:
                self._save_blocking_crash_recovery_record(
                    profile_uuid=profile_uuid,
                    route_plan=route_plan,
                )
            except CrashRecoveryStateError as exc:
                self.log(
                    "error",
                    "log.kill_switch.crash_record.blocking_failed",
                    details=str(exc),
                )
            else:
                self.log("ok", "log.kill_switch.crash_record.blocking_saved")
        self._protected_reconnect_scheduled = True
        self.log("warning", "log.kill_switch.recovery.tunnel_lost")
        QTimer.singleShot(
            600,
            lambda: self._start_protected_reconnect(automatic=True),
        )

    def _start_protected_reconnect(self, *, automatic: bool) -> None:
        self._protected_reconnect_scheduled = False
        if self._connection_busy or not self.kill_switch_runtime.feature_enabled:
            return
        try:
            if network_manager.is_connected():
                self._last_connected_state = True
                self.update_connection_status(force=True)
                return
        except Exception as exc:
            self._show_error(exc)
            return

        baseline = self._kill_switch_probe_baseline
        route_plan = self._kill_switch_route_plan
        profile_uuid = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()
        if baseline is None or route_plan is None or not profile_uuid:
            error = AppError(
                "error.kill_switch_existing_lock.title",
                "error.kill_switch_existing_lock.message",
                details=(
                    "Protected reconnect requires the profile UUID, probe baseline, "
                    "and exact firewall route from the current app session."
                ),
            )
            if automatic:
                self.log("error", "log.kill_switch.recovery.reconnect_unavailable")
            self._show_error(error)
            return

        self._connection_busy = True
        self._update_controls()
        self.log(
            "info",
            "log.kill_switch.recovery.automatic_reconnect"
            if automatic
            else "log.kill_switch.recovery.manual_reconnect",
        )
        existing_session = self._kill_switch_session

        def job() -> _ProtectedReconnectOutcome:
            events: list[RecoveryEvent] = []
            session = existing_session or KillSwitchSessionClient(timeout=120.0)
            try:
                if existing_session is not None:
                    try:
                        session.open()
                        session.status()
                    except Exception:
                        try:
                            session.close()
                        except Exception:
                            pass
                        session = KillSwitchSessionClient(timeout=120.0)

                orchestrator = KillSwitchRecoveryOrchestrator(
                    session=session,
                    vpn_backend=network_manager,
                    event_sink=events.append,
                )
                result = orchestrator.reconnect(
                    profile_uuid=profile_uuid,
                    route_plan=route_plan,
                    blocked_path_probe=baseline.ordinary_path_is_blocked,
                )
                self._save_connected_crash_recovery_record(
                    profile_uuid=result.profile_uuid,
                    route_plan=result.route_plan,
                )
                return _ProtectedReconnectOutcome(
                    profile_uuid=result.profile_uuid,
                    session=session,
                    status=result.firewall_status,
                    route_plan=result.route_plan,
                    events=tuple(events),
                )
            except Exception as exc:
                status: KillSwitchStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                try:
                    still_connected = network_manager.is_connected()
                except Exception as vpn_status_exc:
                    if not status_error:
                        status_error = str(vpn_status_exc)
                else:
                    if still_connected:
                        status_error = (
                            "Protected reconnect failed while NetworkManager still reports "
                            "an active VPN; the combined protection state is unverified."
                        )
                raise _KillSwitchRecoveryJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                    route_plan=route_plan,
                    baseline=baseline,
                    events=tuple(events),
                ) from exc

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _ProtectedReconnectOutcome)
            self._connection_busy = False
            self._log_recovery_events(outcome.events)
            if self._kill_switch_session is not outcome.session:
                self._close_kill_switch_session()
            self._kill_switch_session = outcome.session
            self._set_cached_kill_switch_status(outcome.status)
            self._kill_switch_route_plan = outcome.route_plan
            self._kill_switch_probe_baseline = baseline
            self.log("ok", "log.kill_switch.crash_record.connected_saved")
            self.settings.setValue(
                "connection/profile_uuid",
                outcome.profile_uuid,
            )
            self.settings.sync()
            self._last_connected_state = True
            self.log("ok", "log.kill_switch.recovery.reconnect_complete")
            self._update_controls()
            self.update_connection_status(force=True)
            self._release_initial_region_refresh_if_safe()
            self.refresh_public_info(show_errors=False)
            self._rebuild_tray_menu()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            cause = error
            if isinstance(error, _KillSwitchRecoveryJobFailure):
                cause = error.cause
                self._log_recovery_events(error.events)
                self._kill_switch_probe_baseline = error.baseline
                self._kill_switch_route_plan = error.route_plan
                if self._kill_switch_session is not error.session:
                    self._close_kill_switch_session()
                self._kill_switch_session = error.session
                self._set_cached_kill_switch_status(
                    error.status,
                    error=error.status_error,
                )
            self._last_connected_state = False
            self.log("error", "log.kill_switch.recovery.reconnect_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(self._friendly_kill_switch_error(cause))

        self._run_worker(job, on_success=success, on_failure=failure)

    def _switch_protected_region(
        self,
        *,
        region: Region,
        credentials: Credentials,
    ) -> None:
        baseline = self._kill_switch_probe_baseline
        current_route = self._kill_switch_route_plan
        current_profile = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()
        if baseline is None or current_route is None or not current_profile:
            self._restore_active_region_selection()
            self._show_error(
                AppError(
                    "error.kill_switch_existing_lock.title",
                    "error.kill_switch_existing_lock.message",
                    details=(
                        "Protected server switching requires the current profile UUID, "
                        "probe baseline, and exact firewall route from this app session."
                    ),
                )
            )
            return

        self._connection_busy = True
        self._update_controls()
        region_name = localized_region_name(region, language())
        self.log("info", "log.kill_switch.recovery.switch_requested", region=region_name)
        config_path = cache_dir() / f"{network_manager.INTERFACE_NAME}.conf"
        existing_session = self._kill_switch_session

        def job() -> _ProtectedServerSwitchOutcome:
            events: list[RecoveryEvent] = []
            session = existing_session or KillSwitchSessionClient(timeout=120.0)
            retained_route: FirewallRoutePlan | None = current_route
            try:
                create_wireguard_config(
                    config_path=config_path,
                    credentials=credentials,
                    region=region,
                )
                candidate = PreparedServerSwitch.create(config_path=config_path)
                if existing_session is not None:
                    try:
                        session.open()
                        session.status()
                    except Exception:
                        try:
                            session.close()
                        except Exception:
                            pass
                        session = KillSwitchSessionClient(timeout=120.0)

                orchestrator = KillSwitchRecoveryOrchestrator(
                    session=session,
                    vpn_backend=network_manager,
                    event_sink=events.append,
                )

                def resolve_existing_physical_interface(endpoint: str) -> str:
                    interface = discover_physical_interface(endpoint)
                    if interface not in current_route.physical_interfaces:
                        raise RuntimeError(
                            "The physical network interface changed during the protected "
                            "server switch; this transition is deferred to the dedicated "
                            "Wi-Fi/LAN recovery stage."
                        )
                    return interface

                result = orchestrator.switch_server(
                    current_profile_uuid=current_profile,
                    current_route_plan=current_route,
                    candidate=candidate,
                    blocked_path_probe=baseline.ordinary_path_is_blocked,
                    physical_interface_resolver=resolve_existing_physical_interface,
                )
                retained_route = FirewallRoutePlan.from_connection_plan(
                    result.connection_plan
                )
                self._save_connected_crash_recovery_record(
                    profile_uuid=result.profile_uuid,
                    route_plan=retained_route,
                )
                return _ProtectedServerSwitchOutcome(
                    profile_uuid=result.profile_uuid,
                    session=session,
                    status=result.firewall_status,
                    route_plan=retained_route,
                    events=tuple(events),
                )
            except Exception as exc:
                if (
                    isinstance(exc, ProtectedServerSwitchError)
                    and exc.old_vpn_disconnected
                ):
                    retained_route = None
                status: KillSwitchStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                try:
                    still_connected = network_manager.is_connected()
                except Exception as vpn_status_exc:
                    if not status_error:
                        status_error = str(vpn_status_exc)
                else:
                    if still_connected and not status_error:
                        status_error = (
                            "Protected server switching failed while NetworkManager still "
                            "reports a VPN connection; protection state requires attention."
                        )
                raise _KillSwitchRecoveryJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                    route_plan=retained_route,
                    baseline=baseline,
                    events=tuple(events),
                ) from exc
            finally:
                try:
                    config_path.unlink(missing_ok=True)
                except OSError:
                    pass

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _ProtectedServerSwitchOutcome)
            self._connection_busy = False
            self._log_recovery_events(outcome.events)
            if self._kill_switch_session is not outcome.session:
                self._close_kill_switch_session()
            self._kill_switch_session = outcome.session
            self._set_cached_kill_switch_status(outcome.status)
            self._kill_switch_route_plan = outcome.route_plan
            self._kill_switch_probe_baseline = baseline
            self.log("ok", "log.kill_switch.crash_record.connected_saved")
            self._active_region_id = region.region_id
            self._active_region_fallback = region.name
            self.settings.setValue("connection/selected_region_id", region.region_id)
            self.settings.setValue("connection/active_region_id", region.region_id)
            self.settings.setValue("connection/active_region_name", region.name)
            self.settings.setValue("connection/profile_uuid", outcome.profile_uuid)
            self.settings.sync()
            self._restore_active_region_selection()
            self._last_connected_state = True
            self.log("ok", "log.kill_switch.recovery.switch_complete", region=region_name)
            self._update_controls()
            self.update_connection_status(force=True)
            self.refresh_public_info(show_errors=False)
            self._rebuild_tray_menu()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            cause = error
            if isinstance(error, _KillSwitchRecoveryJobFailure):
                cause = error.cause
                self._log_recovery_events(error.events)
                self._kill_switch_probe_baseline = error.baseline
                self._kill_switch_route_plan = error.route_plan
                if self._kill_switch_session is not error.session:
                    self._close_kill_switch_session()
                self._kill_switch_session = error.session
                self._set_cached_kill_switch_status(
                    error.status,
                    error=error.status_error,
                )
            try:
                still_connected: bool | None = network_manager.is_connected()
            except Exception:
                still_connected = None
            if still_connected is not None:
                self._last_connected_state = still_connected
            if still_connected is True:
                self._restore_active_region_selection()
            elif still_connected is False:
                self.settings.remove("connection/profile_uuid")
                self.settings.sync()
            self.log("error", "activity.switch_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(self._friendly_kill_switch_error(cause))

        self._run_worker(job, on_success=success, on_failure=failure)

    def disconnect(self, *, after_disconnect: Callable[[], None] | None = None) -> None:
        if self._connection_busy:
            return

        kill_switch_enabled = self.kill_switch_runtime.feature_enabled
        baseline = self._kill_switch_probe_baseline
        if kill_switch_enabled and baseline is None:
            self._show_error(
                AppError(
                    "error.kill_switch_existing_lock.title",
                    "error.kill_switch_existing_lock.message",
                    details=(
                        "Protected disconnect requires the pre-connection probe baseline "
                        "from the current app session."
                    ),
                )
            )
            return

        self._connection_busy = True
        self._intentional_disconnect_in_progress = True
        self._update_controls()
        self.status_detail_label.setText(tr("activity.disconnecting"))
        self.log("info", "activity.disconnecting")

        profile_uuid = str(
            self.settings.value("connection/profile_uuid", "")
        ).strip()
        existing_session = self._kill_switch_session
        existing_guard_session = self._ipv6_guard_session

        def job() -> _NormalGuardDisconnectOutcome | _ProtectedDisconnectOutcome:
            if not kill_switch_enabled:
                session = existing_guard_session or KillSwitchSessionClient(timeout=120.0)
                try:
                    lifecycle = IPv6GuardLifecycle(
                        session=session,
                        vpn_backend=network_manager,
                    )
                    result = lifecycle.disconnect(profile_uuid)
                    return _NormalGuardDisconnectOutcome(
                        session=session,
                        status=result.guard_status,
                    )
                except Exception as exc:
                    status: IPv6GuardStatus | None = None
                    status_error = ""
                    guard_retained = True
                    vpn_connected: bool | None = None
                    cause: BaseException = exc
                    if isinstance(exc, IPv6GuardDisconnectError):
                        cause = exc.cause or exc
                        status = exc.guard_status
                        guard_retained = exc.guard_retained
                        vpn_connected = not exc.vpn_disconnected
                    else:
                        try:
                            if session.is_open:
                                status = session.ipv6_guard_status()
                        except Exception as status_exc:
                            status_error = str(status_exc)
                    raise _IPv6GuardJobFailure(
                        cause,
                        session=session,
                        status=status,
                        status_error=status_error,
                        guard_retained=guard_retained,
                        vpn_connected=vpn_connected,
                    ) from exc

            assert baseline is not None
            events: list[ConnectionEvent] = []
            session = existing_session or KillSwitchSessionClient(timeout=120.0)
            try:
                if existing_session is not None:
                    try:
                        session.open()
                        session.status()
                    except Exception:
                        try:
                            session.close()
                        except Exception:
                            pass
                        session = KillSwitchSessionClient(timeout=120.0)

                orchestrator = KillSwitchConnectionOrchestrator(
                    session=session,
                    vpn_backend=network_manager,
                    event_sink=events.append,
                )
                result = orchestrator.disconnect_intentionally(
                    profile_uuid=profile_uuid,
                    kill_switch_enabled=True,
                    blocked_path_probe=baseline.ordinary_path_is_blocked,
                )
                if result.firewall_status is None:
                    raise RuntimeError(
                        "Protected disconnect returned no verified helper status."
                    )
                return _ProtectedDisconnectOutcome(
                    session=session,
                    status=result.firewall_status,
                    events=tuple(events),
                )
            except Exception as exc:
                status: KillSwitchStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                raise _KillSwitchJobFailure(
                    exc,
                    session=session,
                    status=status,
                    status_error=status_error,
                    baseline=baseline,
                    events=tuple(events),
                ) from exc

        def success(result: Any) -> None:
            self._connection_busy = False
            self._intentional_disconnect_in_progress = False
            if isinstance(result, _ProtectedDisconnectOutcome):
                self._log_connection_events(result.events)
                if self._kill_switch_session is not result.session:
                    self._close_kill_switch_session()
                self._kill_switch_session = result.session
                self._set_cached_kill_switch_status(result.status)
                self._kill_switch_probe_baseline = None
                self._kill_switch_route_plan = None
                self._close_kill_switch_session()
            else:
                assert isinstance(result, _NormalGuardDisconnectOutcome)
                if self._ipv6_guard_session is not result.session:
                    self._close_ipv6_guard_session()
                self._ipv6_guard_session = result.session
                self._set_cached_ipv6_guard_status(result.status)
                self._set_ipv6_guard_expected(False)
                self.log("ok", "log.ipv6_guard.released")
                self._close_ipv6_guard_session()
                self._kill_switch_probe_baseline = None
                self._kill_switch_route_plan = None
                self._set_cached_kill_switch_status(None)
                self._close_kill_switch_session()

            self.settings.remove("connection/profile_uuid")
            self.settings.sync()
            self._clear_crash_recovery_record_after_safe_release()
            self._last_connected_state = False
            self.log("ok", "log.disconnected")
            self.public_info = None
            self._update_controls()
            self.update_connection_status(force=True)
            self._rebuild_tray_menu()
            if after_disconnect is not None:
                after_disconnect()

        def failure(error: BaseException) -> None:
            self._connection_busy = False
            self._intentional_disconnect_in_progress = False
            cause = error
            if isinstance(error, _IPv6GuardJobFailure):
                cause = error.cause
                self._set_cached_ipv6_guard_status(
                    error.status,
                    error=error.status_error,
                )
                if error.guard_retained:
                    self._set_ipv6_guard_expected(True)
                    if error.session is not None:
                        if self._ipv6_guard_session is not error.session:
                            self._close_ipv6_guard_session()
                        self._ipv6_guard_session = error.session
                    self.log("warning", "log.ipv6_guard.retained_after_failure")
                else:
                    self._set_ipv6_guard_expected(False)
                    self._close_ipv6_guard_session()
                if error.vpn_connected is not None:
                    self._last_connected_state = error.vpn_connected
            elif isinstance(error, _KillSwitchJobFailure):
                cause = error.cause
                self._log_connection_events(error.events)
                self._kill_switch_probe_baseline = error.baseline
                if self._kill_switch_session is not error.session:
                    self._close_kill_switch_session()
                self._kill_switch_session = error.session
                self._set_cached_kill_switch_status(
                    error.status,
                    error=error.status_error,
                )
            try:
                still_connected: bool | None = network_manager.is_connected()
            except Exception:
                still_connected = None
            if still_connected is False:
                self.settings.remove("connection/profile_uuid")
                self.settings.sync()
            self.log("error", "activity.disconnect_failed")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(self._friendly_kill_switch_error(cause))

        self._run_worker(job, on_success=success, on_failure=failure)

    def _disconnected_kill_switch_may_block(
        self,
        *,
        connected: bool | None = None,
    ) -> bool:
        if connected is None:
            try:
                connected = network_manager.is_connected()
            except Exception:
                return self.kill_switch_runtime.feature_enabled
        if connected or not self.kill_switch_runtime.feature_enabled:
            return False
        if self._kill_switch_status_error:
            return True
        if self._kill_switch_status is not None:
            return self._kill_switch_status.present
        return self._startup_kill_switch_reconciliation_required()

    def _networkmanager_unknown_view_state(self, error: BaseException) -> KillSwitchViewState:
        status = self._kill_switch_status
        return derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=self.kill_switch_runtime.feature_enabled,
                vpn_connected=bool(self._last_connected_state),
                table_present=False if status is None else status.present,
                table_verified=False if status is None else status.verified,
                problems=() if status is None else status.problems,
                error=f"NetworkManager status could not be verified: {error}",
            )
        )

    def _show_suppressed_public_info(self) -> None:
        if self._kill_switch_view_state.mode.value == "blocking":
            self.ip_value.setText("—")
            self.country_value.setText("—")
            self.ipv6_value.setText(tr("status.ipv6_blocked"))
            self.dns_value.setText("—")
        else:
            self.ip_value.setText(tr("common.unknown"))
            self.country_value.setText(tr("common.unknown"))
            self.ipv6_value.setText(tr("common.unknown"))
            self.dns_value.setText(tr("common.unknown"))

    def _release_ipv6_guard_after_unexpected_vpn_loss(
        self,
        *,
        after_release: Callable[[], None] | None = None,
    ) -> None:
        if self._ipv6_guard_release_scheduled or self._connection_busy:
            return
        if self.kill_switch_runtime.feature_enabled or not self._ipv6_guard_expected():
            if after_release is not None:
                after_release()
            return
        session = self._ipv6_guard_session
        if session is None:
            audit = self._packaged_helper_manager.audit()
            if not audit.current:
                self._set_cached_ipv6_guard_status(
                    self._ipv6_guard_status,
                    error=(
                        "The IPv6 guard is expected, but the exact packaged helper "
                        f"boundary is not available: {audit.details}"
                    ),
                )
                self.log("warning", "log.ipv6_guard.release_deferred")
                self._update_controls()
                self.update_connection_status(force=True)
                self._show_error(
                    AppError(
                        "error.ipv6_guard.title",
                        "error.ipv6_guard.release_deferred_message",
                        details=audit.details,
                    )
                )
                return
            # A crash or broker timeout can leave the kernel guard alive while
            # this GUI no longer owns an authenticated session.  Open a fresh
            # fixed helper session and still require verified VPN-down before
            # any guard removal.
            session = KillSwitchSessionClient(timeout=120.0)

        self._ipv6_guard_release_scheduled = True
        self.log("info", "log.ipv6_guard.releasing_after_loss")

        def job() -> _NormalGuardDisconnectOutcome:
            try:
                result = IPv6GuardLifecycle(
                    session=session,
                    vpn_backend=network_manager,
                ).release_after_verified_vpn_loss()
                return _NormalGuardDisconnectOutcome(
                    session=session,
                    status=result.guard_status,
                )
            except Exception as exc:
                status: IPv6GuardStatus | None = None
                status_error = ""
                try:
                    if session.is_open:
                        status = session.ipv6_guard_status()
                except Exception as status_exc:
                    status_error = str(status_exc)
                cause = exc.cause if isinstance(exc, IPv6GuardDisconnectError) and exc.cause else exc
                raise _IPv6GuardJobFailure(
                    cause,
                    session=session,
                    status=status,
                    status_error=status_error,
                    guard_retained=True,
                    vpn_connected=False,
                ) from exc

        def success(result: Any) -> None:
            outcome = result
            assert isinstance(outcome, _NormalGuardDisconnectOutcome)
            self._ipv6_guard_release_scheduled = False
            self._set_cached_ipv6_guard_status(outcome.status)
            self._set_ipv6_guard_expected(False)
            self.settings.remove("connection/profile_uuid")
            self.settings.sync()
            self._close_ipv6_guard_session()
            self.public_info = None
            self.log("ok", "log.ipv6_guard.released_after_loss")
            self._update_controls()
            self.update_connection_status(force=True)
            if after_release is not None:
                after_release()

        def failure(error: BaseException) -> None:
            self._ipv6_guard_release_scheduled = False
            cause = error
            if isinstance(error, _IPv6GuardJobFailure):
                cause = error.cause
                self._set_cached_ipv6_guard_status(
                    error.status,
                    error=error.status_error or str(cause),
                )
            self._set_ipv6_guard_expected(True)
            self.log("warning", "log.ipv6_guard.retained_after_loss")
            self._update_controls()
            self.update_connection_status(force=True)
            self._show_error(
                AppError(
                    "error.ipv6_guard.title",
                    "error.ipv6_guard.retained_message",
                    details=f"{type(cause).__name__}: {cause}",
                )
            )

        self._run_worker(job, on_success=success, on_failure=failure)

    def update_connection_status(self, force: bool = False) -> None:
        # During an intentional disconnect the worker deliberately moves through
        # VPN-down/firewall-still-active and then firewall-released boundaries.
        # The 3-second background poll must not render a transient error from an
        # intermediate state. Success/failure commits a verified result with
        # force=True immediately after the transaction finishes.
        if self._intentional_disconnect_in_progress and self._connection_busy and not force:
            return
        if self._stage4_preview:
            self._set_stage4_preview_state(
                self._stage4_preview_index,
                log_transition=False,
            )
            return
        try:
            connected = network_manager.is_connected()
        except Exception as exc:
            self._apply_kill_switch_view_state(
                self._networkmanager_unknown_view_state(exc),
                log_transition=not self._connection_busy,
            )
            self._show_suppressed_public_info()
            self._update_controls()
            if force:
                self._rebuild_tray_menu()
            return

        changed = (
            self._last_connected_state is None
            or connected != self._last_connected_state
        )
        previous = self._last_connected_state
        self._last_connected_state = connected

        if (
            not connected
            and self.kill_switch_runtime.feature_enabled
            and self._kill_switch_status is None
            and not self._kill_switch_status_error
            and not self._startup_kill_switch_reconciliation_required()
        ):
            # Remembered preference only: there is no crash/reconciliation hint
            # and no live VPN, so do not claim an error merely because this new
            # GUI process has not opened a privileged helper session.  ARMED does
            # not claim active firewall protection; the helper is authorized when
            # a protected connection is actually requested.
            state = derive_kill_switch_view_state(
                KillSwitchObservation.create(
                    feature_enabled=True,
                    vpn_connected=False,
                    table_present=False,
                    table_verified=False,
                )
            )
        else:
            state = self.kill_switch_runtime.view_state(
                vpn_connected=connected,
            )
        self._apply_kill_switch_view_state(
            state,
            log_transition=not self._connection_busy,
        )

        disconnected_lock = self._disconnected_kill_switch_may_block(
            connected=connected,
        )
        unexpected_protected_loss = (
            changed
            and previous is True
            and not connected
            and not self._connection_busy
            and self.kill_switch_runtime.feature_enabled
            and disconnected_lock
        )
        if connected:
            if self.kill_switch_runtime.feature_enabled:
                ipv6_verified = bool(
                    self._kill_switch_status is not None
                    and self._kill_switch_status.protection_active
                )
            else:
                ipv6_verified = bool(
                    self._ipv6_guard_status is not None
                    and self._ipv6_guard_status.protection_active
                    and not self._ipv6_guard_status_error
                )
            self.ipv6_value.setText(
                tr("status.ipv6_blocked")
                if ipv6_verified
                else tr("status.ipv6_warning")
            )
            self.dns_value.setText(tr("status.dns_pia"))
            self.connection_button.setText(tr("connection.disconnect"))
            self.toggle_vpn_action.setText(tr("connection.disconnect"))
        elif disconnected_lock:
            self._show_suppressed_public_info()
            action_key = (
                "connection.reconnect"
                if self._protected_reconnect_context_available()
                else "connection.recheck_protection"
            )
            self.connection_button.setText(tr(action_key))
            self.toggle_vpn_action.setText(tr(action_key))
        else:
            guard_still_blocks = (
                not self.kill_switch_runtime.feature_enabled
                and self._ipv6_guard_expected()
                and self._ipv6_guard_status is not None
                and self._ipv6_guard_status.protection_active
                and not self._ipv6_guard_status_error
            )
            self.ipv6_value.setText(
                tr("status.ipv6_blocked")
                if guard_still_blocks
                else tr("status.ipv6_normal")
            )
            self.dns_value.setText(tr("status.dns_system"))
            self.connection_button.setText(tr("connection.connect"))
            self.toggle_vpn_action.setText(tr("connection.connect"))

        if disconnected_lock:
            self._show_suppressed_public_info()
        elif self.public_info is None:
            self.ip_value.setText(tr("status.not_checked"))
            self.country_value.setText(tr("status.not_checked"))
        else:
            self.ip_value.setText(self.public_info.ip_address)
            self.country_value.setText(
                public_country_name(self.public_info.country_code, language())
            )

        unexpected_normal_loss = (
            changed
            and previous is True
            and not connected
            and not self._connection_busy
            and not self.kill_switch_runtime.feature_enabled
            and self._ipv6_guard_expected()
        )
        if unexpected_protected_loss:
            self._schedule_protected_reconnect()
        elif unexpected_normal_loss:
            self.public_info = None
            self.log("warning", "log.ipv6_guard.vpn_lost")
            self._release_ipv6_guard_after_unexpected_vpn_loss()
        elif changed and previous is not None and not self._connection_busy:
            self.log(
                "info",
                "log.external_connected" if connected else "log.external_disconnected",
            )
            if connected:
                self.refresh_public_info(show_errors=False)
            else:
                self.public_info = None

        self._update_controls()
        if force or changed:
            self._rebuild_tray_menu()

    def _update_controls(self) -> None:
        if self._stage4_preview:
            return
        busy = self._connection_busy or self._regions_busy
        has_regions = bool(self.regions)
        network_state_known = True
        try:
            connected = network_manager.is_connected()
        except Exception:
            network_state_known = False
            connected = bool(self._last_connected_state)

        disconnected_lock = (
            self._disconnected_kill_switch_may_block(connected=connected)
            if network_state_known
            else self.kill_switch_runtime.feature_enabled
        )
        self.connection_button.setEnabled(
            network_state_known
            and not busy
            and (has_regions or connected or disconnected_lock)
        )
        self.region_combo.setEnabled(
            network_state_known
            and not busy
            and has_regions
            and (connected or not disconnected_lock)
        )
        self.search_edit.setEnabled(
            network_state_known
            and not busy
            and has_regions
            and (connected or not disconnected_lock)
        )
        self.reload_button.setEnabled(not busy)
        self.ping_button.setEnabled(not busy and has_regions)
        self.ip_refresh_button.setEnabled(
            network_state_known and not self._public_info_busy and not disconnected_lock
        )
        self.reload_action.setEnabled(not busy)
        self.ping_action.setEnabled(not busy and has_regions)
        self.toggle_vpn_action.setEnabled(
            network_state_known and not self._connection_busy
        )
        self.kill_switch_action.setEnabled(
            network_state_known and not busy and not connected
        )
        emergency_relevant = bool(
            self._kill_switch_status is not None
            and self._kill_switch_status.present
            and (not network_state_known or not connected)
        )
        self.emergency_reset_action.setVisible(emergency_relevant)
        self.emergency_reset_action.setEnabled(not busy and emergency_relevant)

    # ------------------------------------------------------------------
    # Public network information
    # ------------------------------------------------------------------
    def refresh_public_info(self, *, show_errors: bool) -> None:
        if self._public_info_busy:
            return
        if self._disconnected_kill_switch_may_block():
            self._show_suppressed_public_info()
            self.ip_refresh_button.setEnabled(False)
            return
        self._public_info_busy = True
        self.ip_value.setText(tr("common.checking"))
        self.country_value.setText(tr("common.checking"))
        self.ip_refresh_button.setEnabled(False)

        def success(result: Any) -> None:
            self._public_info_busy = False
            previous_public_info = self.public_info
            self.public_info = result
            if self._disconnected_kill_switch_may_block():
                self._show_suppressed_public_info()
            else:
                self.ip_value.setText(result.ip_address)
                self.country_value.setText(
                    public_country_name(result.country_code, language())
                )
            self.ip_refresh_button.setEnabled(True)
            # Automatic lifecycle/status refreshes can legitimately reconfirm
            # the same public endpoint in quick succession. Keep the network
            # check itself, but avoid duplicate Live Log noise when nothing
            # changed. An explicit user refresh (show_errors=True) always logs.
            if show_errors or previous_public_info != result:
                self.log(
                    "info",
                    "log.public_info",
                    ip=mask_ip_address(result.ip_address),
                    country=public_country_name(result.country_code, language()),
                )

        def failure(error: BaseException) -> None:
            self._public_info_busy = False
            if self._disconnected_kill_switch_may_block():
                self._show_suppressed_public_info()
            else:
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
        network_state_known = True
        try:
            connected = network_manager.is_connected()
        except Exception:
            network_state_known = False
            connected = bool(self._last_connected_state)
        disconnected_lock = (
            self._disconnected_kill_switch_may_block(connected=connected)
            if network_state_known
            else self.kill_switch_runtime.feature_enabled
        )

        state = self._kill_switch_view_state
        if connected:
            active_region = self._region_by_id(self._active_region_id)
            active_name = (
                localized_region_name(active_region, language())
                if active_region is not None
                else self._active_region_fallback or tr("common.unknown")
            )
            tray_status_text = tr("tray.status_connected", region=active_name)
        else:
            tray_status_text = tr("tray.status_disconnected")
        status_action = QAction(tray_status_text, menu)
        status_action.setIcon(status_dot_icon(state.icon_state))
        # Indicator only: one colored icon, no duplicate text bullet, and no
        # click action.
        status_action.setEnabled(False)
        menu.addAction(status_action)
        menu.addSeparator()

        if connected:
            disconnect_action = QAction(tr("connection.disconnect"), menu)
            disconnect_action.setEnabled(
                network_state_known and not self._connection_busy
            )
            disconnect_action.triggered.connect(
                lambda checked=False: self.disconnect()
            )
            menu.addAction(disconnect_action)
        else:
            connect_action = QAction(menu)
            if not network_state_known:
                connect_action.setText(tr("connection.connect"))
                connect_action.setEnabled(False)
            elif disconnected_lock:
                reconnect_ready = self._protected_reconnect_context_available()
                connect_action.setText(
                    tr(
                        "connection.reconnect"
                        if reconnect_ready
                        else "connection.recheck_protection"
                    )
                )
                connect_action.setEnabled(not self._connection_busy)
                if reconnect_ready:
                    connect_action.triggered.connect(
                        lambda checked=False: self._start_protected_reconnect(
                            automatic=False
                        )
                    )
                else:
                    connect_action.triggered.connect(
                        lambda checked=False: self._recheck_kill_switch_status()
                    )
            else:
                last_region = self._last_selected_region()
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
        locations_menu.setEnabled(
            network_state_known
            and bool(self.regions)
            and not self._connection_busy
            and not disconnected_lock
        )

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
            ][:20]
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

    def _expanded_log_size(self) -> QSize:
        # The Kill-Switch status card made the compact content taller than it
        # was in 0.5.0.  Derive the expanded height from the actual log-panel
        # minimum instead of assuming the old fixed 780px total.  This keeps
        # the log action buttons below the text view across desktop themes.
        extra_height = (
            self.log_panel.minimumSizeHint().height()
            + self.main_layout.spacing()
        )
        return QSize(
            LOG_SIZE.width(),
            max(LOG_SIZE.height(), COMPACT_SIZE.height() + extra_height),
        )

    def _log_visibility_changed(self, visible: bool) -> None:
        self.live_log_action.blockSignals(True)
        self.live_log_action.setChecked(visible)
        self.live_log_action.blockSignals(False)
        self.settings.setValue("ui/live_log", visible)

        # Both modes are intentionally fixed-size. The expanded mode only
        # adds the log immediately below the connection section.
        target = self._expanded_log_size() if visible else COMPACT_SIZE
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.setFixedSize(target)
        self.settings.sync()
        if visible:
            QTimer.singleShot(0, self._scroll_live_log_to_end)

    def _apply_live_log_setting(self, *, initial: bool) -> None:
        del initial
        visible = bool_value(self.settings, "ui/live_log", False)
        self.live_log_action.blockSignals(True)
        self.live_log_action.setChecked(visible)
        self.live_log_action.blockSignals(False)
        self.log_panel.setVisible(visible)
        self.setFixedSize(self._expanded_log_size() if visible else COMPACT_SIZE)
        if visible:
            QTimer.singleShot(0, self._scroll_live_log_to_end)

    # ------------------------------------------------------------------
    # About and application lifecycle
    # ------------------------------------------------------------------
    def show_about(self) -> None:
        AboutDialog(self).exec()

    def show_window(self) -> None:
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.raise_()
        self.activateWindow()
        if self.log_panel.isVisible():
            QTimer.singleShot(0, self._scroll_live_log_to_end)

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
        except Exception as exc:
            self._show_error(exc)
            return

        if not connected:
            if self._disconnected_kill_switch_may_block(connected=False):
                self._recheck_kill_switch_status(
                    after_absent=self._final_quit,
                    announce_absent=False,
                )
                return
            if self._ipv6_guard_expected():
                self._release_ipv6_guard_after_unexpected_vpn_loss(
                    after_release=self._final_quit,
                )
                return
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
            if self.kill_switch_runtime.feature_enabled:
                QMessageBox.warning(
                    self,
                    tr("kill_switch.quit_connected_title"),
                    tr("kill_switch.quit_connected_message"),
                )
                return
            self._final_quit()
        elif behavior == "disconnect":
            self.disconnect(after_disconnect=self._final_quit)

    def _final_quit(self) -> None:
        self._close_kill_switch_session()
        self._close_ipv6_guard_session()
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
