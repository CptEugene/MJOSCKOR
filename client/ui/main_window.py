from __future__ import annotations

import asyncio
import ctypes
import html
from pathlib import Path
import random
import sys
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QGraphicsOpacityEffect,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from client.input.input_monitor import InputMonitor
from client.input.process_detection import ProcessDetectionMonitor
from client.models.audio import AudioSettings
from client.network.control_client import ControlClient
from client.network.server_discovery import ServerDiscoveryClient
from client.overlay.overlay_widget import (
    MissionTextOverlayWidget,
    OverlayTalker,
    RadioChatOverlayWidget,
    RadioOverlayWidget,
    VideoOverlayWidget,
    KneeboardOverlayWidget,
)
from client.services.admin_chat_commands import AdminChatCommand, parse_admin_chat_command
from client.services.audio_runtime import AudioRuntime
from client.services.fleet_tree_binding import FleetTreeBindingService
from client.services.font_loader import build_font
from client.services.qt_runtime import AsyncBridge
from client.services.soundtrack_service import SoundtrackService
from client.services.settings_store import SettingsStore
from client.services.ui_sound_player import UiSoundPlayer
from client.services.video_overlay_service import VideoOverlayService
from client.ui.admin_dialog import AdminDialog
from client.ui.channel_card import ChannelCardState, ChannelCardWidget
from client.ui.fleet_tree_widget import FleetTreeWidget, SlotActivation
from client.ui.message_dialog import AppMessageDialog
from client.ui.notice_dialog import NoticeDialog
from client.ui.settings_dialog import SettingsDialog
from shared.constants.channels import (
    CHANNEL_KEY_BY_TAG,
    CHANNEL_LIMITS,
    CHANNEL_TAG_ORDER,
    DEFAULT_CHANNEL_ASSIGNMENTS,
    clamp_channel_assignment,
)
from shared.constants.app_version import APP_VERSION
from shared.constants.paths import runtime_paths
from shared.constants.security import ADMIN_PASSWORD
from shared.models.fleet_tree import ROLE_PERMISSIONS, FleetTreeModel, RoleName
from shared.models.fleet_tree_codec import decode_fleet_tree, encode_fleet_tree
from shared.models.fleet_tree_ids import ensure_unique_tree_ids


class MaydayMainWindow(QMainWindow):
    controlStateSignal = Signal()
    treeSnapshotSignal = Signal()
    presenceSnapshotSignal = Signal()
    chatStateSignal = Signal()
    kneeboardStateSignal = Signal()
    noticeStateSignal = Signal()
    memberStateSignal = Signal()
    soundtrackCommandSignal = Signal(dict)
    missionOverlaySignal = Signal(dict)
    videoOverlaySignal = Signal(dict)
    serverDiscoverySignal = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MAYDAY")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1120, 575)

        self._settings_store = SettingsStore()
        self._input_monitor = InputMonitor()
        self._process_detection = ProcessDetectionMonitor()
        self._settings_dialog = SettingsDialog(self._input_monitor, self)
        self._admin_dialog = AdminDialog(self)
        self._notice_dialog = NoticeDialog(self)
        self._overlay_widget = RadioOverlayWidget()
        self._chat_overlay_widget = RadioChatOverlayWidget()
        self._mission_overlay_widget = MissionTextOverlayWidget()
        self._video_overlay_widget: VideoOverlayWidget | None = None
        self._kneeboard_overlay_widget = KneeboardOverlayWidget()
        self._audio_runtime = AudioRuntime()
        self._soundtrack_service = SoundtrackService()
        self._video_overlay_service = VideoOverlayService()
        self._control_client = ControlClient()
        self._server_discovery = ServerDiscoveryClient()
        self._fleet_binding = FleetTreeBindingService()
        self._async = AsyncBridge()
        self._ui_sound_player = UiSoundPlayer(self)
        self._audio_started = False
        self._device_list_loaded = False
        self._active_ptt_key: int | None = None
        self._active_binding_channel: str | None = None
        self._active_channel_tag = "squad"
        self._binding_release_deadline = 0.0
        self._binding_release_grace_seconds = 0.35
        self._channel_cards: dict[str, list[ChannelCardWidget]] = {}
        self._channel_states: dict[str, ChannelCardState] = {}
        self._channel_bindings = ["1", "2", "3", "4"]
        self._kneeboard_binding = "F10"
        self._last_notified_error = ""
        self._last_confirmed_own_slot_id = ""
        self._chat_hotkey_latched = False
        self._kneeboard_hotkey_latched = False
        self._kneeboard_overlay_enabled = False
        self._chat_previous_foreground_hwnd: int | None = None
        self._pending_soundtrack_command: dict | None = None
        self._pending_soundtrack_timer = QTimer(self)
        self._pending_soundtrack_timer.setSingleShot(True)
        self._pending_soundtrack_timer.timeout.connect(self._play_pending_soundtrack)
        self._pending_video_overlay_command: dict | None = None
        self._pending_video_overlay_timer = QTimer(self)
        self._pending_video_overlay_timer.setSingleShot(True)
        self._pending_video_overlay_timer.timeout.connect(self._play_pending_video_overlay)
        self._star_citizen_detected = False
        self._last_chat_message_signature: tuple[int, int, str] | None = None
        self._closing = False
        self._suppress_kneeboard_edit_signal = False
        self._main_chat_history: QTextBrowser | None = None
        self._main_chat_input: QLineEdit | None = None
        self._main_chat_send_button: QPushButton | None = None
        self._kneeboard_editor: QPlainTextEdit | None = None
        self._kneeboard_status_label: QLabel | None = None
        self._kneeboard_admin_button: QPushButton | None = None
        self._assignment_value_labels: dict[str, QLabel] = {}
        self._squadmate_list: QTextBrowser | None = None
        self._home_nickname_edit: QLineEdit | None = None
        self._home_nickname_button: QPushButton | None = None
        self._home_nickname_save_button: QPushButton | None = None
        self._server_panel_title: QLabel | None = None
        self._server_panel_subtitle: QLabel | None = None
        self._server_disconnect_button: QPushButton | None = None
        self._server_list_layout: QVBoxLayout | None = None
        self._server_entries: list[dict[str, object]] = []
        self._notice_body_label: QLabel | None = None
        self._kneeboard_update_timer = QTimer(self)
        self._kneeboard_update_timer.setSingleShot(True)
        self._kneeboard_update_timer.timeout.connect(self._commit_kneeboard_update)
        self._page_fade: QPropertyAnimation | None = None
        self._page_fade_out: QPropertyAnimation | None = None
        self._page_slide: QPropertyAnimation | None = None
        self._page_slide_out: QPropertyAnimation | None = None
        self._page_fade_overlay: QLabel | None = None
        self._drag_offset: QPoint | None = None
        self._background_label: QLabel | None = None
        self._background_next_label: QLabel | None = None
        self._background_pixmaps = self._load_background_pixmaps()
        self._background_index = random.randrange(len(self._background_pixmaps)) if self._background_pixmaps else 0
        self._background_timer = QTimer(self)
        self._background_timer.timeout.connect(self._advance_background_image)
        self._background_slide_current: QPropertyAnimation | None = None
        self._background_slide_next: QPropertyAnimation | None = None
        self._visual_stage_container: QFrame | None = None
        self._visual_stage_label: QLabel | None = None
        self._visual_stage_next_label: QLabel | None = None
        self._visual_stage_pixmaps = self._load_visual_stage_pixmaps()
        self._visual_stage_index = 0
        self._visual_stage_timer = QTimer(self)
        self._visual_stage_timer.timeout.connect(self._advance_visual_stage_image)
        self._visual_stage_slide_current: QPropertyAnimation | None = None
        self._visual_stage_slide_next: QPropertyAnimation | None = None

        self._server_value_labels: list[QLabel] = []
        self._fleet_tree_widget: FleetTreeWidget | None = None
        self._fleet_tree_dialog: QDialog | None = None
        self._admin_media_status_label: QLabel | None = None
        self._soundtrack_list: QListWidget | None = None
        self._soundtrack_track_edit: QLineEdit | None = None
        self._soundtrack_volume_edit: QLineEdit | None = None
        self._soundtrack_fade_edit: QLineEdit | None = None
        self._video_list: QListWidget | None = None
        self._video_track_edit: QLineEdit | None = None
        self._video_volume_edit: QLineEdit | None = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._settings_nav_buttons: dict[str, QPushButton] = {}
        self._settings_stack: QStackedWidget | None = None
        self._page_stack: QStackedWidget | None = None

        root = QWidget(self)
        root.setObjectName("appShell")
        self._background_label = QLabel(root)
        self._background_label.setObjectName("backgroundImage")
        self._background_label.setScaledContents(False)
        self._background_label.lower()
        self._background_next_label = QLabel(root)
        self._background_next_label.setObjectName("backgroundImage")
        self._background_next_label.setScaledContents(False)
        self._background_next_label.hide()
        self._background_next_label.lower()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())

        content = QWidget(root)
        content.setObjectName("contentSurface")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 18, 24, 16)
        content_layout.setSpacing(14)
        content_layout.addWidget(self._build_header())
        content_layout.addWidget(self._build_pages(), 1)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(self._stylesheet())

        self._settings_dialog.save_button.clicked.connect(lambda: self._save_settings(show_feedback=True))
        self._settings_dialog.mic_level_start_button.clicked.connect(self._start_microphone_meter)
        self._settings_dialog.mic_level_stop_button.clicked.connect(self._stop_microphone_meter)
        self._admin_dialog.saveRequested.connect(self._save_tree_text)

        self.controlStateSignal.connect(self._sync_control_state)
        self.treeSnapshotSignal.connect(self._sync_tree_snapshot)
        self.presenceSnapshotSignal.connect(self._sync_presence_snapshot)
        self.chatStateSignal.connect(self._sync_chat_overlay)
        self.kneeboardStateSignal.connect(self._sync_kneeboard_text)
        self.noticeStateSignal.connect(self._sync_notice_text)
        self.memberStateSignal.connect(self._sync_member_list)
        self.soundtrackCommandSignal.connect(self._handle_soundtrack_command)
        self.missionOverlaySignal.connect(self._handle_mission_overlay_command)
        self.videoOverlaySignal.connect(self._handle_video_overlay_command)
        self.serverDiscoverySignal.connect(self._sync_discovered_servers)
        self._control_client.on_state_changed(self.controlStateSignal.emit)
        self._control_client.on_tree_changed(self.treeSnapshotSignal.emit)
        self._control_client.on_presence_changed(self.presenceSnapshotSignal.emit)
        self._control_client.on_chat_changed(self.chatStateSignal.emit)
        self._control_client.on_kneeboard_changed(self.kneeboardStateSignal.emit)
        self._control_client.on_notice_changed(self.noticeStateSignal.emit)
        self._control_client.on_members_changed(self.memberStateSignal.emit)
        self._control_client.on_soundtrack_command(self.soundtrackCommandSignal.emit)
        self._control_client.on_mission_overlay_command(self.missionOverlaySignal.emit)
        self._control_client.on_video_overlay_command(self.videoOverlaySignal.emit)
        self._server_discovery.on_changed(self.serverDiscoverySignal.emit)
        self._chat_overlay_widget.messageSubmitted.connect(self._submit_chat_message)
        self._chat_overlay_widget.inputClosed.connect(self._restore_previous_foreground_window)
        self._load_initial_settings()
        QTimer.singleShot(0, self._finish_startup)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_realtime_ui)
        self._status_timer.start(16)
        self._tick_realtime_ui()
        self._server_discovery.start()
        if len(self._visual_stage_pixmaps) > 1:
            self._visual_stage_timer.start(7000)

    def _load_background_pixmaps(self) -> list[QPixmap]:
        background_dirs = [runtime_paths().assets_dir / "backgrounds"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            background_dirs.insert(0, Path(meipass) / "assets" / "backgrounds")
        pixmaps: list[QPixmap] = []
        for backgrounds_dir in background_dirs:
            for name in ("1.png", "2.png", "4.jpg", "5.jpg", "7.jpg", "8.jpg", "9.png"):
                image_path = backgrounds_dir / name
                if not image_path.exists():
                    continue
                pixmap = QPixmap(str(image_path))
                if not pixmap.isNull():
                    pixmaps.append(self._rounded_pixmap(pixmap, 8))
            if pixmaps:
                break
        return pixmaps

    @staticmethod
    def _rounded_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
        rounded = QPixmap(pixmap.size())
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return rounded

    def _load_visual_stage_pixmaps(self) -> list[QPixmap]:
        visual_dirs = [runtime_paths().assets_dir / "visual_stage"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            visual_dirs.insert(0, Path(meipass) / "assets" / "visual_stage")
        pixmaps: list[QPixmap] = []
        for visual_dir in visual_dirs:
            for name in (
                "stage_01.jpg",
                "stage_02.jpg",
                "stage_03.jpg",
                "stage_04.jpg",
                "stage_05.jpg",
                "stage_06.jpg",
            ):
                image_path = visual_dir / name
                if not image_path.exists():
                    continue
                pixmap = QPixmap(str(image_path))
                if not pixmap.isNull():
                    pixmaps.append(self._stage_pixmap(pixmap))
            if pixmaps:
                break
        return pixmaps

    def _stage_pixmap(self, pixmap: QPixmap) -> QPixmap:
        target_width = 546
        target_height = 410
        scaled = pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target_width) // 2)
        y = max(0, (scaled.height() - target_height) // 2)
        return self._rounded_pixmap(scaled.copy(x, y, target_width, target_height), 8)

    def _advance_visual_stage_image(self) -> None:
        if (
            self._visual_stage_container is None
            or self._visual_stage_label is None
            or self._visual_stage_next_label is None
            or len(self._visual_stage_pixmaps) < 2
            or self._visual_stage_slide_current is not None
        ):
            return
        next_index = (self._visual_stage_index + 1) % len(self._visual_stage_pixmaps)
        width = self._visual_stage_container.width()
        height = self._visual_stage_container.height()
        if width <= 0 or height <= 0:
            return

        self._visual_stage_next_label.setPixmap(self._visual_stage_pixmaps[next_index])
        self._visual_stage_label.setGeometry(0, 0, width, height)
        self._visual_stage_next_label.setGeometry(width, 0, width, height)
        self._visual_stage_next_label.show()

        current_slide = QPropertyAnimation(self._visual_stage_label, b"geometry", self)
        current_slide.setDuration(820)
        current_slide.setStartValue(QRect(0, 0, width, height))
        current_slide.setEndValue(QRect(-width, 0, width, height))
        current_slide.setEasingCurve(QEasingCurve.Type.InOutCubic)

        next_slide = QPropertyAnimation(self._visual_stage_next_label, b"geometry", self)
        next_slide.setDuration(820)
        next_slide.setStartValue(QRect(width, 0, width, height))
        next_slide.setEndValue(QRect(0, 0, width, height))
        next_slide.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def finish_visual_slide() -> None:
            self._visual_stage_index = next_index
            self._visual_stage_label.setPixmap(self._visual_stage_next_label.pixmap())
            self._visual_stage_label.setGeometry(0, 0, width, height)
            self._visual_stage_next_label.hide()
            self._visual_stage_next_label.setPixmap(QPixmap())
            self._visual_stage_slide_current = None
            self._visual_stage_slide_next = None

        next_slide.finished.connect(finish_visual_slide)
        self._visual_stage_slide_current = current_slide
        self._visual_stage_slide_next = next_slide
        current_slide.start()
        next_slide.start()

    def _sync_background_image(self) -> None:
        if self._background_label is None or not self._background_pixmaps:
            return
        size = self.centralWidget().size() if self.centralWidget() is not None else self.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        cropped = self._background_frame(self._background_pixmaps[self._background_index], size)
        self._background_label.setGeometry(0, 0, size.width(), size.height())
        self._background_label.setPixmap(cropped)
        self._background_label.lower()
        if self._background_next_label is not None and not self._background_next_label.isVisible():
            self._background_next_label.setGeometry(size.width(), 0, size.width(), size.height())

    def _background_frame(self, pixmap: QPixmap, size) -> QPixmap:  # noqa: ANN001
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        return scaled.copy(x, y, size.width(), size.height())

    def _advance_background_image(self) -> None:
        if (
            self._background_label is None
            or self._background_next_label is None
            or len(self._background_pixmaps) < 2
            or self._background_slide_current is not None
        ):
            return
        size = self.centralWidget().size() if self.centralWidget() is not None else self.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        next_index = (self._background_index + 1) % len(self._background_pixmaps)
        self._background_next_label.setPixmap(self._background_frame(self._background_pixmaps[next_index], size))
        self._background_label.setGeometry(0, 0, size.width(), size.height())
        self._background_next_label.setGeometry(size.width(), 0, size.width(), size.height())
        self._background_next_label.show()
        self._background_next_label.lower()
        self._background_label.lower()

        current_slide = QPropertyAnimation(self._background_label, b"geometry", self)
        current_slide.setDuration(950)
        current_slide.setStartValue(QRect(0, 0, size.width(), size.height()))
        current_slide.setEndValue(QRect(-size.width(), 0, size.width(), size.height()))
        current_slide.setEasingCurve(QEasingCurve.Type.InOutCubic)

        next_slide = QPropertyAnimation(self._background_next_label, b"geometry", self)
        next_slide.setDuration(950)
        next_slide.setStartValue(QRect(size.width(), 0, size.width(), size.height()))
        next_slide.setEndValue(QRect(0, 0, size.width(), size.height()))
        next_slide.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def finish_background_slide() -> None:
            self._background_index = next_index
            self._background_label.setPixmap(self._background_next_label.pixmap())
            self._background_label.setGeometry(0, 0, size.width(), size.height())
            self._background_next_label.hide()
            self._background_next_label.setPixmap(QPixmap())
            self._background_slide_current = None
            self._background_slide_next = None
            self._background_label.lower()
            self._background_next_label.lower()

        next_slide.finished.connect(finish_background_slide)
        self._background_slide_current = current_slide
        self._background_slide_next = next_slide
        current_slide.start()
        next_slide.start()

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("headerFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 0, 6, 0)

        title = QLabel("MAYDAY 작전 콘솔")
        title.setFont(build_font(13, 800))
        subtitle = QLabel("함대 통신, 지휘 트리, 음성 오버레이")
        subtitle.setObjectName("subtitle")
        subtitle.setFont(build_font(8, 600))

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(1)
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)

        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("versionLabel")
        version.setFont(build_font(9, 600))
        close_button = QPushButton("X")
        close_button.setObjectName("topCloseButton")
        close_button.setToolTip("MAYDAY 종료")
        close_button.setFont(build_font(9, 900))
        close_button.clicked.connect(self.close)

        layout.addLayout(title_wrap)
        layout.addStretch(1)
        layout.addWidget(version)
        layout.addWidget(close_button)
        return frame

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sideRail")
        sidebar.setFixedWidth(58)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(8)

        brand = QPushButton("")
        brand.setObjectName("sideBrandButton")
        brand.setToolTip("메인")
        brand.setProperty("selected", False)
        icon_path = runtime_paths().assets_dir / "icon.png"
        if icon_path.exists():
            brand.setIcon(QIcon(str(icon_path)))
            brand.setIconSize(QRect(0, 0, 24, 24).size())
        else:
            brand.setText("M")
            brand.setFont(build_font(13, 900))
        brand.clicked.connect(lambda: self._show_page("home"))
        self._nav_buttons["home"] = brand
        layout.addWidget(brand)
        layout.addSpacing(6)

        layout.addWidget(self._make_nav_button("F", "플릿 트리", lambda: self._show_page("fleet"), "fleet"))
        layout.addWidget(self._make_nav_button("V", "음성 / 채널", lambda: self._show_page("voice"), "voice"))
        layout.addStretch(1)
        layout.addWidget(self._make_nav_button("?", "도움말", self._notice_dialog.show))
        layout.addWidget(self._make_nav_button("S", "설정", lambda: self._show_page("settings"), "settings"))
        return sidebar

    def _make_nav_button(self, label: str, tooltip: str, handler=None, page_key: str | None = None) -> QPushButton:  # noqa: ANN001
        button = QPushButton(label)
        button.setObjectName("sideNavButton")
        button.setToolTip(tooltip)
        button.setFont(build_font(9, 800))
        if handler is not None:
            button.clicked.connect(handler)
        if page_key is not None:
            button.setProperty("selected", False)
            self._nav_buttons[page_key] = button
        return button

    def _build_pages(self) -> QStackedWidget:
        self._page_stack = QStackedWidget()
        self._page_stack.setObjectName("pageStack")
        self._page_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._page_stack.setFixedHeight(494)
        self._page_stack.addWidget(self._build_home_page())
        self._page_stack.addWidget(self._build_fleet_page())
        self._page_stack.addWidget(self._build_voice_page())
        self._page_stack.addWidget(self._build_settings_page())
        QTimer.singleShot(0, lambda: self._show_page("home", animate=False))
        return self._page_stack

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("contentPage")
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)

        layout.addWidget(self._build_server_list_panel(), 0, 0, 1, 2)
        layout.addWidget(self._build_status_panel(), 1, 0)
        layout.addWidget(self._build_notice_panel(), 1, 1)
        layout.addWidget(self._build_visual_panel(), 0, 2, 2, 1)
        layout.setRowStretch(0, 4)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 3)
        return page

    def _build_fleet_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("contentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_tree_panel(), 1)
        return page

    def _build_voice_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("contentPage")
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)
        layout.addWidget(self._build_channel_panel(), 0, 0, 2, 1)
        layout.addWidget(self._build_main_chat_panel(), 0, 1)
        layout.addWidget(self._build_kneeboard_panel(), 1, 1)
        layout.addWidget(self._build_assignment_panel(), 0, 2, 2, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(2, 1)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("contentPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        nav = QFrame(page)
        nav.setObjectName("panel")
        nav.setFixedWidth(170)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(14, 14, 14, 14)
        nav_layout.setSpacing(8)
        nav_title = QLabel("설정")
        nav_title.setFont(build_font(11, 900))
        nav_layout.addWidget(nav_title)
        nav_layout.addWidget(self._make_settings_nav_button("사운드", "sound", lambda: self._show_settings_tab("sound")))
        nav_layout.addWidget(self._make_settings_nav_button("기타", "other", lambda: self._show_settings_tab("other")))
        nav_layout.addWidget(self._make_settings_nav_button("관리자", "admin", lambda: self._show_settings_tab("admin")))
        nav_layout.addStretch(1)
        layout.addWidget(nav)

        panel = QFrame(page)
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(10)
        title = QLabel("설정")
        title.setFont(build_font(13, 900))
        subtitle = QLabel("플릿, 사운드, 입력 설정")
        subtitle.setObjectName("mutedText")
        subtitle.setFont(build_font(9, 600))
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

        self._settings_dialog.set_embedded_mode(True)
        self._settings_stack = QStackedWidget(panel)
        self._settings_stack.addWidget(self._settings_dialog)
        self._settings_stack.addWidget(self._build_admin_media_page())
        panel_layout.addWidget(self._settings_stack, 1)
        layout.addWidget(panel, 1)
        QTimer.singleShot(0, lambda: self._show_settings_tab("sound"))
        return page

    def _make_settings_nav_button(self, label: str, key: str, handler) -> QPushButton:  # noqa: ANN001
        button = QPushButton(label)
        button.setObjectName("settingsNavButton")
        button.setProperty("selected", False)
        button.clicked.connect(handler)
        self._settings_nav_buttons[key] = button
        return button

    def _show_settings_tab(self, tab_key: str) -> None:
        if tab_key == "fleet":
            self._open_admin_dialog()
            return
        elif tab_key == "sound":
            if not self._device_list_loaded:
                self._refresh_audio_device_lists()
            self._settings_dialog.select_section(0)
            if self._settings_stack is not None:
                self._settings_stack.setCurrentIndex(0)
        elif tab_key == "other":
            if not self._device_list_loaded:
                self._refresh_audio_device_lists()
            self._settings_dialog.select_section(1)
            if self._settings_stack is not None:
                self._settings_stack.setCurrentIndex(0)
        elif tab_key == "admin":
            if not self._ensure_admin_authenticated():
                return
            self._refresh_soundtrack_tracks()
            self._refresh_video_tracks()
            if self._settings_stack is not None:
                self._settings_stack.setCurrentIndex(1)
        for key, button in self._settings_nav_buttons.items():
            button.setProperty("selected", key == tab_key)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _build_admin_media_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        soundtrack = self._build_dj_deck(
            title="사운드트랙 데크",
            hint=f"음악 라이브러리\n{self._short_runtime_path(self._soundtrack_service.music_dir)}",
            list_attr="soundtrack",
            play_handler=self._emit_soundtrack_play,
            stop_handler=self._emit_soundtrack_stop,
            refresh_handler=self._refresh_soundtrack_tracks,
            include_fade=True,
        )
        video = self._build_dj_deck(
            title="영상 오버레이 데크",
            hint=f"영상 라이브러리\n{self._short_runtime_path(self._video_overlay_service.video_dir)}",
            list_attr="video",
            play_handler=self._emit_video_overlay_play,
            stop_handler=self._emit_video_overlay_stop,
            refresh_handler=self._refresh_video_tracks,
            include_fade=False,
        )

        layout.addWidget(soundtrack, 5)
        layout.addWidget(video, 5)

        status_panel = QFrame(page)
        status_panel.setObjectName("subPanel")
        status_panel.setFixedWidth(126)
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(12, 12, 12, 12)
        status_title = QLabel("관리자 상태")
        status_title.setFont(build_font(9, 800))
        self._admin_media_status_label = QLabel("준비됨")
        self._admin_media_status_label.setObjectName("mutedText")
        self._admin_media_status_label.setWordWrap(True)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self._admin_media_status_label)
        status_layout.addStretch(1)
        layout.addWidget(status_panel)
        return page

    def _short_runtime_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(runtime_paths().root_dir))
        except ValueError:
            return path.name

    def _build_dj_deck(
        self,
        *,
        title: str,
        hint: str,
        list_attr: str,
        play_handler,
        stop_handler,
        refresh_handler,
        include_fade: bool,
    ) -> QFrame:  # noqa: ANN001
        deck = QFrame()
        deck.setObjectName("subPanel")
        layout = QVBoxLayout(deck)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setFont(build_font(10, 900))
        hint_label = QLabel(hint)
        hint_label.setObjectName("mutedText")
        hint_label.setWordWrap(True)
        hint_label.setFont(build_font(7, 600))
        layout.addWidget(title_label)
        layout.addWidget(hint_label)

        media_list = QListWidget()
        media_list.setObjectName("mediaDeckList")
        media_list.setMinimumHeight(190)
        layout.addWidget(media_list, 1)

        track_edit = QLineEdit()
        track_edit.setPlaceholderText("트랙 / 영상 ID")
        volume_edit = QLineEdit("10")
        volume_edit.setPlaceholderText("볼륨")

        if list_attr == "soundtrack":
            self._soundtrack_list = media_list
            self._soundtrack_track_edit = track_edit
            self._soundtrack_volume_edit = volume_edit
            media_list.itemSelectionChanged.connect(self._sync_soundtrack_selection)
        else:
            self._video_list = media_list
            self._video_track_edit = track_edit
            self._video_volume_edit = volume_edit
            media_list.itemSelectionChanged.connect(self._sync_video_selection)

        layout.addWidget(QLabel("선택"))
        layout.addWidget(track_edit)
        layout.addWidget(QLabel("볼륨"))
        layout.addWidget(volume_edit)

        if include_fade:
            self._soundtrack_fade_edit = QLineEdit("1200")
            self._soundtrack_fade_edit.setPlaceholderText("페이드 ms")
            layout.addWidget(QLabel("페이드 ms"))
            layout.addWidget(self._soundtrack_fade_edit)

        controls = QHBoxLayout()
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(refresh_handler)
        play = QPushButton("재생")
        play.setObjectName("primaryButton")
        play.clicked.connect(play_handler)
        stop = QPushButton("정지")
        stop.clicked.connect(stop_handler)
        controls.addWidget(refresh)
        controls.addWidget(play)
        controls.addWidget(stop)
        layout.addLayout(controls)
        return deck

    def _build_operation_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("heroPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel("작전 제어")
        title.setObjectName("heroTitle")
        title.setFont(build_font(20, 900))
        subtitle = QLabel("통신을 준비하고 플릿 트리에 참가해 지휘 채널을 정리합니다.")
        subtitle.setObjectName("mutedText")
        subtitle.setFont(build_font(9, 600))
        layout.addWidget(title)
        layout.addWidget(subtitle)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(10)
        connect = QPushButton("접속")
        connect.setObjectName("primaryButton")
        connect.clicked.connect(self._connect_to_server)
        settings = QPushButton("오디오 / PTT")
        settings.clicked.connect(self._open_settings_dialog)
        fleet = QPushButton("플릿 에디터")
        fleet.clicked.connect(self._open_admin_dialog)
        notice = QPushButton("도움말")
        notice.clicked.connect(self._notice_dialog.show)
        actions.addWidget(connect, 0, 0)
        actions.addWidget(settings, 0, 1)
        actions.addWidget(fleet, 1, 0)
        actions.addWidget(notice, 1, 1)
        layout.addLayout(actions)
        return panel

    def _build_attention_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("주의")
        title.setFont(build_font(10, 800))
        layout.addWidget(title)

        lines = [
            ("관리자", "게임 PTT에는 관리자 권한 필요"),
            ("송신", "효과 없는 원음 송신"),
            ("수신", "HOMEWORLD_FLEET_COMMS"),
            ("입력", "조이스틱 바인딩 시 감지"),
        ]
        for label, value in lines:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setObjectName("mutedText")
            detail = QLabel(value)
            detail.setObjectName("statusPill")
            detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(detail)
            layout.addLayout(row)
        layout.addStretch(1)
        return panel

    def _show_page(self, page_key: str, *, animate: bool = True) -> None:
        page_indices = {"home": 0, "fleet": 1, "voice": 2, "settings": 3}
        index = page_indices.get(page_key, 0)
        stack = self._page_stack
        if stack is None:
            return
        for key, button in self._nav_buttons.items():
            button.setProperty("selected", key == page_key)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()
        if not animate or stack.currentIndex() == index:
            stack.setCurrentIndex(index)
            return
        self._switch_page(index)

    def _switch_page(self, index: int) -> None:
        stack = self._page_stack
        if stack is None:
            return
        old_index = stack.currentIndex()
        if old_index == index:
            return
        direction = 1 if index > old_index else -1
        travel = 28
        old_pixmap = stack.grab()
        overlay_parent = stack.parentWidget()
        overlay = QLabel(overlay_parent)
        overlay.setPixmap(old_pixmap)
        overlay.setGeometry(stack.geometry())
        overlay.show()
        overlay.raise_()
        stack.setCurrentIndex(index)

        new_widget = stack.currentWidget()
        new_widget.move(direction * travel, 0)
        new_effect = QGraphicsOpacityEffect(new_widget)
        new_effect.setOpacity(0.0)
        new_widget.setGraphicsEffect(new_effect)
        fade_in = QPropertyAnimation(new_effect, b"opacity", self)
        fade_in.setDuration(260)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.OutQuart)

        slide_in = QPropertyAnimation(new_widget, b"pos", self)
        slide_in.setDuration(260)
        slide_in.setStartValue(QPoint(direction * travel, 0))
        slide_in.setEndValue(QPoint(0, 0))
        slide_in.setEasingCurve(QEasingCurve.Type.OutQuart)

        def finish_new_page() -> None:
            new_widget.setGraphicsEffect(None)
            new_widget.move(0, 0)

        fade_in.finished.connect(finish_new_page)

        old_effect = QGraphicsOpacityEffect(overlay)
        old_effect.setOpacity(1.0)
        overlay.setGraphicsEffect(old_effect)
        fade_out = QPropertyAnimation(old_effect, b"opacity", self)
        fade_out.setDuration(260)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutQuart)

        start_pos = stack.geometry().topLeft()
        slide_out = QPropertyAnimation(overlay, b"pos", self)
        slide_out.setDuration(260)
        slide_out.setStartValue(start_pos)
        slide_out.setEndValue(start_pos - QPoint(direction * 14, 0))
        slide_out.setEasingCurve(QEasingCurve.Type.OutQuart)
        fade_out.finished.connect(overlay.deleteLater)

        self._page_fade_overlay = overlay
        self._page_fade = fade_in
        self._page_fade_out = fade_out
        self._page_slide = slide_in
        self._page_slide_out = slide_out
        fade_in.start()
        slide_in.start()
        fade_out.start()
        slide_out.start()

    def _build_visual_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("imageStagePanel")
        panel.setFixedHeight(494)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("비주얼 스테이지")
        title.setFont(build_font(10, 800))
        hint = QLabel("이미지 / 작전 아트워크")
        hint.setObjectName("mutedText")
        hint.setFont(build_font(9, 600))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)

        image_slot = QFrame(panel)
        image_slot.setObjectName("imageDropZone")
        image_slot.setFixedSize(546, 410)
        image_slot.setContentsMargins(0, 0, 0, 0)
        self._visual_stage_container = image_slot
        self._visual_stage_label = QLabel(image_slot)
        self._visual_stage_label.setObjectName("visualStageImage")
        self._visual_stage_label.setGeometry(0, 0, 546, 410)
        self._visual_stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._visual_stage_label.setScaledContents(False)
        self._visual_stage_next_label = QLabel(image_slot)
        self._visual_stage_next_label.setObjectName("visualStageImage")
        self._visual_stage_next_label.setGeometry(546, 0, 546, 410)
        self._visual_stage_next_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._visual_stage_next_label.setScaledContents(False)
        self._visual_stage_next_label.hide()
        if self._visual_stage_pixmaps:
            self._visual_stage_label.setPixmap(self._visual_stage_pixmaps[self._visual_stage_index])
        else:
            self._visual_stage_label.setText("이미지 영역")
            self._visual_stage_label.setObjectName("imageStageText")
            self._visual_stage_label.setFont(build_font(22, 900))
        layout.addWidget(image_slot, 1, Qt.AlignmentFlag.AlignCenter)
        return panel

    def _build_channel_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("채널 컨트롤")
        title.setFont(build_font(10, 700))
        layout.addWidget(title)

        cards = [
            ("squad", ChannelCardState("스쿼드", DEFAULT_CHANNEL_ASSIGNMENTS[0], "1", active=True, enabled=False)),
            ("hq", ChannelCardState("지휘부", DEFAULT_CHANNEL_ASSIGNMENTS[1], "2", enabled=False)),
            ("atc", ChannelCardState("관제/함선", DEFAULT_CHANNEL_ASSIGNMENTS[2], "3", enabled=False)),
            ("general", ChannelCardState("일반", DEFAULT_CHANNEL_ASSIGNMENTS[3], "4", enabled=False)),
        ]
        for key, state in cards:
            state = self._channel_states.setdefault(key, state)
            widget = ChannelCardWidget(state)
            widget.channelStepRequested.connect(
                lambda _name, step, channel_tag=key: self._step_channel_assignment(channel_tag, step)
            )
            self._channel_cards.setdefault(key, []).append(widget)
            layout.addWidget(widget)
        return panel

    def _build_status_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("로컬 상태")
        title.setFont(build_font(10, 700))
        layout.addWidget(title)

        server_row = QHBoxLayout()
        server_row.addWidget(QLabel("서버"))
        server_row.addStretch(1)
        server_value_label = QLabel("오프라인")
        server_value_label.setObjectName("statusOffline")
        self._server_value_labels.append(server_value_label)
        server_row.addWidget(server_value_label)
        layout.addLayout(server_row)

        nickname_label = QLabel("닉네임")
        nickname_label.setObjectName("mutedText")
        nickname_row = QHBoxLayout()
        nickname_row.setSpacing(8)
        self._home_nickname_button = QPushButton("user")
        self._home_nickname_button.setObjectName("nicknameDisplayButton")
        self._home_nickname_button.clicked.connect(self._start_home_nickname_edit)
        self._home_nickname_edit = QLineEdit(panel)
        self._home_nickname_edit.setObjectName("homeNicknameEdit")
        self._home_nickname_edit.setPlaceholderText("닉네임")
        self._home_nickname_edit.setMaxLength(32)
        self._home_nickname_edit.returnPressed.connect(self._commit_home_nickname)
        self._home_nickname_edit.hide()
        self._home_nickname_save_button = QPushButton("저장")
        self._home_nickname_save_button.setObjectName("nicknameSaveButton")
        self._home_nickname_save_button.clicked.connect(self._commit_home_nickname)
        self._home_nickname_save_button.hide()
        nickname_row.addWidget(self._home_nickname_button, 1)
        nickname_row.addWidget(self._home_nickname_edit, 1)
        nickname_row.addWidget(self._home_nickname_save_button)
        layout.addWidget(nickname_label)
        layout.addLayout(nickname_row)
        return panel

    def _start_home_nickname_edit(self) -> None:
        if self._home_nickname_button is not None:
            self._home_nickname_button.hide()
        if self._home_nickname_edit is not None:
            self._home_nickname_edit.show()
            self._home_nickname_edit.setFocus()
            self._home_nickname_edit.selectAll()
        if self._home_nickname_save_button is not None:
            self._home_nickname_save_button.show()

    def _commit_home_nickname(self) -> None:
        if self._home_nickname_edit is None:
            return
        nickname = self._home_nickname_edit.text().strip() or "user"
        settings = self._settings_dialog.to_settings()
        if settings.nickname == nickname:
            self._sync_home_nickname(settings.nickname)
            return
        settings.nickname = nickname
        self._settings_dialog.load_from_settings(settings)
        self._settings_store.save(settings)
        self._control_client.configure(
            callsign=settings.nickname,
            server_address=settings.server_address,
            server_password=settings.server_password,
            channel_assignments=settings.channel_assignments,
        )
        self._sync_home_nickname(settings.nickname)

    def _build_server_list_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        self._server_panel_title = QLabel("서버 목록")
        self._server_panel_title.setFont(build_font(10, 800))
        self._server_panel_subtitle = QLabel("감지된 MAYDAY 서버")
        self._server_panel_subtitle.setObjectName("mutedText")
        self._server_panel_subtitle.setFont(build_font(8, 600))
        title_wrap.addWidget(self._server_panel_title)
        title_wrap.addWidget(self._server_panel_subtitle)
        self._server_disconnect_button = QPushButton("연결 해제")
        self._server_disconnect_button.setObjectName("disconnectServerButton")
        self._server_disconnect_button.clicked.connect(self._disconnect_from_server)
        self._server_disconnect_button.hide()
        header.addLayout(title_wrap)
        header.addStretch(1)
        header.addWidget(self._server_disconnect_button)
        layout.addLayout(header)

        self._server_list_layout = QVBoxLayout()
        self._server_list_layout.setSpacing(8)
        layout.addLayout(self._server_list_layout, 1)
        self._refresh_server_list_panel()
        return panel

    def _refresh_server_list_panel(self) -> None:
        if self._server_list_layout is None:
            return
        self._clear_layout(self._server_list_layout)
        if self._control_client.state.connected:
            if self._server_disconnect_button is not None:
                self._server_disconnect_button.show()
            if self._server_panel_title is not None:
                self._server_panel_title.setText("멤버 목록")
            if self._server_panel_subtitle is not None:
                self._server_panel_subtitle.setText("접속 중인 사용자")
            if not self._control_client.state.member_entries:
                empty = QLabel("접속 중인 멤버 없음")
                empty.setObjectName("mutedText")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._server_list_layout.addWidget(empty, 1)
                return
            for entry in self._control_client.state.member_entries:
                self._server_list_layout.addWidget(self._build_member_entry(entry))
            self._server_list_layout.addStretch(1)
            return
        if self._server_disconnect_button is not None:
            self._server_disconnect_button.hide()
        if self._server_panel_title is not None:
            self._server_panel_title.setText("서버 목록")
        if self._server_panel_subtitle is not None:
            self._server_panel_subtitle.setText("감지된 MAYDAY 서버")
        if not self._server_entries:
            empty = QLabel("감지된 서버 없음")
            empty.setObjectName("mutedText")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._server_list_layout.addWidget(empty, 1)
            return
        for entry in self._server_entries:
            self._server_list_layout.addWidget(self._build_server_entry(entry))
        self._server_list_layout.addStretch(1)

    def _sync_discovered_servers(self, entries: object) -> None:
        if not isinstance(entries, list):
            entries = []
        self._server_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("address", "")).strip()
        ]
        self._refresh_server_list_panel()

    def _sync_member_list(self) -> None:
        self._refresh_server_list_panel()

    def _build_member_entry(self, entry: dict[str, object]) -> QFrame:
        card = QFrame()
        card.setObjectName("serverEntry")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        name = QLabel(str(entry.get("callsign", "")) or "알 수 없음")
        name.setFont(build_font(9, 800))
        detail = QLabel(f"{entry.get('role', '-') or '-'} / {entry.get('slot_id', '-') or '-'}")
        detail.setObjectName("mutedText")
        detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(name, 1)
        layout.addWidget(detail)
        return card

    def _build_server_entry(self, entry: dict[str, object]) -> QFrame:
        card = QFrame()
        card.setObjectName("serverEntry")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)

        name = QLabel(str(entry.get("name", "MAYDAY 서버")))
        name.setFont(build_font(9, 800))
        name.setMinimumWidth(120)
        address = QLabel(str(entry.get("address", "127.0.0.1")))
        address.setObjectName("mutedText")
        address.hide()
        count = QLabel(f"{int(entry.get('players', 0))}명 접속")
        count.setObjectName("mutedText")
        lock_state = QLabel("비밀번호 필요" if entry.get("requires_password") else "공개 서버")
        lock_state.setObjectName("mutedText")
        lock_state.hide()
        join = QPushButton("참가")
        join.setObjectName("joinServerButton")
        join.setFixedWidth(56)
        join.clicked.connect(lambda checked=False, payload=entry: self._join_discovered_server(payload))
        layout.addWidget(name, 1)
        layout.addWidget(count)
        layout.addStretch(1)
        layout.addWidget(join)
        return card

    @staticmethod
    def _clear_layout(layout) -> None:  # noqa: ANN001
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                MaydayMainWindow._clear_layout(child_layout)

    def _build_notice_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel("공지")
        title.setFont(build_font(10, 800))
        body = QLabel("공지사항 영역입니다. 서버 공지, 작전 안내, 업데이트 내용을 이곳에 표시할 예정입니다.")
        body.setObjectName("mutedText")
        body.setWordWrap(True)
        body.setFont(build_font(9, 600))
        self._notice_body_label = body
        layout.addWidget(title)
        layout.addWidget(body, 1)
        return panel

    def _sync_notice_text(self) -> None:
        if self._notice_body_label is None:
            return
        self._notice_body_label.setText(self._control_client.state.notice_text.strip() or "서버 공지가 없습니다.")

    def _join_discovered_server(self, entry: dict[str, object]) -> None:
        password, ok = self._prompt_password("서버 비밀번호", "서버 비밀번호를 입력하세요:")
        if not ok:
            return
        settings = self._settings_dialog.to_settings()
        settings.server_address = str(entry.get("address", settings.server_address))
        settings.server_password = password
        self._settings_dialog.load_from_settings(settings)
        self._save_settings(show_feedback=False)
        self._connect_to_server()

    def _build_tree_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("플릿 트리")
        title.setFont(build_font(10, 700))
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        self._fleet_tree_widget = FleetTreeWidget()
        self._fleet_tree_widget.slotActivated.connect(self._join_slot)
        self._fleet_tree_widget.createFleetRequested.connect(self._open_admin_dialog)
        layout.addWidget(self._fleet_tree_widget, 1)
        return panel

    def _open_fleet_tree_dialog(self) -> None:
        if self._fleet_tree_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("플릿 트리")
            dialog.resize(760, 560)
            dialog.setModal(False)
            dialog.setStyleSheet(self._stylesheet())
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(self._build_tree_panel())
            self._fleet_tree_dialog = dialog
        self._sync_tree_snapshot()
        self._fleet_tree_dialog.show()
        self._fleet_tree_dialog.raise_()
        self._fleet_tree_dialog.activateWindow()

    def _build_tree_bottom_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._build_main_chat_panel(), 1)
        row.addWidget(self._build_kneeboard_panel(), 1)
        return row

    def _build_main_chat_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("subPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("채팅")
        title.setFont(build_font(9, 700))
        layout.addWidget(title)

        self._main_chat_history = QTextBrowser(panel)
        self._main_chat_history.setObjectName("mainChatHistory")
        self._main_chat_history.setFrameShape(QFrame.Shape.NoFrame)
        self._main_chat_history.setReadOnly(True)
        self._main_chat_history.setOpenLinks(False)
        self._main_chat_history.setOpenExternalLinks(False)
        self._main_chat_history.document().setDocumentMargin(0)
        layout.addWidget(self._main_chat_history, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._main_chat_input = QLineEdit(panel)
        self._main_chat_input.setPlaceholderText("채팅 입력 후 Enter")
        self._main_chat_input.returnPressed.connect(self._submit_main_chat_message)
        self._main_chat_send_button = QPushButton("전송")
        self._main_chat_send_button.clicked.connect(self._submit_main_chat_message)
        input_row.addWidget(self._main_chat_input, 1)
        input_row.addWidget(self._main_chat_send_button)
        layout.addLayout(input_row)
        return panel

    def _build_kneeboard_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("subPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("작전 메모")
        title.setFont(build_font(9, 700))
        self._kneeboard_status_label = QLabel("읽기 전용")
        self._kneeboard_status_label.setObjectName("kneeboardStatus")
        self._kneeboard_admin_button = QPushButton("관리자 편집")
        self._kneeboard_admin_button.clicked.connect(self._request_kneeboard_admin_edit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._kneeboard_status_label)
        header.addWidget(self._kneeboard_admin_button)
        layout.addLayout(header)

        self._kneeboard_editor = QPlainTextEdit(panel)
        self._kneeboard_editor.setObjectName("kneeboardEditor")
        self._kneeboard_editor.setReadOnly(True)
        self._kneeboard_editor.textChanged.connect(self._on_kneeboard_text_changed)
        layout.addWidget(self._kneeboard_editor, 1)
        return panel

    def _build_assignment_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(230)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("스쿼드 상태")
        title.setFont(build_font(10, 800))
        layout.addWidget(title)

        for key, label in (
            ("fleet", "플릿"),
            ("wing", "윙"),
            ("squad", "스쿼드"),
        ):
            caption = QLabel(label.upper())
            caption.setObjectName("mutedText")
            caption.setFont(build_font(8, 700))
            value = QLabel("-")
            value.setObjectName("assignmentValue")
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setMinimumHeight(46)
            value.setFont(build_font(10, 800))
            self._assignment_value_labels[key] = value
            layout.addWidget(caption)
            layout.addWidget(value, 0, Qt.AlignmentFlag.AlignVCenter)

        members = QLabel("스쿼드원")
        members.setObjectName("mutedText")
        members.setFont(build_font(8, 700))
        self._squadmate_list = QTextBrowser(panel)
        self._squadmate_list.setObjectName("squadmateList")
        self._squadmate_list.setFrameShape(QFrame.Shape.NoFrame)
        self._squadmate_list.setReadOnly(True)
        self._squadmate_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._squadmate_list.document().setDocumentMargin(0)
        layout.addWidget(members)
        layout.addWidget(self._squadmate_list, 1)
        return panel

    def _load_initial_settings(self) -> None:
        loaded = self._settings_store.load()
        if loaded.channel_assignments == [1, 0, 0, 0]:
            loaded.channel_assignments = list(DEFAULT_CHANNEL_ASSIGNMENTS)
            self._settings_store.save(loaded)
        self._settings_dialog.load_from_settings(loaded)
        self._chat_overlay_widget.set_chat_size(loaded.overlay_chat_size)
        self._sync_home_nickname(loaded.nickname)
        self._audio_runtime.apply_settings(
            AudioSettings(
                microphone_device_index=loaded.microphone_device_index,
                microphone_device_name=loaded.microphone_device_name,
                microphone_device_endpoint_id=loaded.microphone_device_endpoint_id,
                speaker_device_index=loaded.speaker_device_index,
                speaker_device_name=loaded.speaker_device_name,
                speaker_device_endpoint_id=loaded.speaker_device_endpoint_id,
                microphone_volume_percent=loaded.microphone_volume,
                speaker_volume_percent=loaded.speaker_volume,
                channel_receive_volumes=loaded.channel_receive_volumes,
                channel_pan_modes=loaded.channel_pan_modes,
            )
        )
        self._soundtrack_service.configure(
            loaded.speaker_device_index,
            loaded.speaker_device_name,
            loaded.speaker_device_endpoint_id,
        )
        self._control_client.configure(
            callsign=loaded.nickname,
            server_address=loaded.server_address,
            server_password=loaded.server_password,
            channel_assignments=self._effective_channel_assignments_for_role(
                loaded.channel_assignments,
                self._control_client.state.selected_role,
            ),
        )
        self._channel_bindings = list(loaded.channel_bindings)
        self._kneeboard_binding = loaded.kneeboard_binding
        self._apply_channel_labels(
            self._effective_channel_assignments_for_role(
                loaded.channel_assignments,
                self._control_client.state.selected_role,
            )
        )
        self._apply_binding_labels(self._channel_bindings)
        self._update_kneeboard_editability()

    def _finish_startup(self) -> None:
        self._input_monitor.start(enable_joystick=self._bindings_use_joystick(self._channel_bindings, self._kneeboard_binding))
        self._process_detection.start()

    def _refresh_audio_device_lists(self) -> None:
        loaded = self._settings_store.load()
        device_state = self._audio_runtime.refresh_devices()
        self._settings_dialog.set_audio_devices(device_state.input_devices, device_state.output_devices)
        self._settings_dialog.load_from_settings(loaded)
        self._device_list_loaded = True

    def _open_settings_dialog(self) -> None:
        self._show_page("settings")
        self._show_settings_tab("sound")

    def _save_settings(self, show_feedback: bool = True) -> None:
        settings = self._settings_dialog.to_settings()
        previous_settings = self._settings_store.load()
        self._settings_store.save(settings)
        self._release_active_ptt()
        effective_assignments = self._effective_channel_assignments_for_role(
            settings.channel_assignments,
            self._control_client.state.selected_role,
        )
        self._control_client.configure(
            callsign=settings.nickname,
            server_address=settings.server_address,
            server_password=settings.server_password,
            channel_assignments=effective_assignments,
        )
        if self._control_client.state.connected:
            self._control_client.update_channel_assignments(effective_assignments)
        self._channel_bindings = list(settings.channel_bindings)
        self._kneeboard_binding = settings.kneeboard_binding
        self._chat_overlay_widget.set_chat_size(settings.overlay_chat_size)
        self._input_monitor.set_joystick_enabled(
            self._bindings_use_joystick(self._channel_bindings, self._kneeboard_binding),
            delay_seconds=0.5,
        )
        self._apply_channel_labels(effective_assignments)
        self._apply_binding_labels(self._channel_bindings)
        self._async.submit(self._apply_runtime_settings_after_save(settings, previous_settings))
        self._sync_home_nickname(settings.nickname)
        if show_feedback:
            self._ui_sound_player.play("Save")
            self._show_info("\uC800\uC7A5 \uC644\uB8CC", "\uC124\uC815\uC774 \uC800\uC7A5\uB418\uC5C8\uC2B5\uB2C8\uB2E4.")

    def _sync_home_nickname(self, nickname: str) -> None:
        nickname = nickname.strip() or "user"
        if self._home_nickname_edit is not None:
            self._home_nickname_edit.blockSignals(True)
            self._home_nickname_edit.setText(nickname)
            self._home_nickname_edit.blockSignals(False)
            self._home_nickname_edit.hide()
        if self._home_nickname_button is not None:
            self._home_nickname_button.setText(nickname)
            self._home_nickname_button.show()
        if self._home_nickname_save_button is not None:
            self._home_nickname_save_button.hide()

    def _step_channel_assignment(self, channel_tag: str, step: int) -> None:
        if channel_tag not in CHANNEL_TAG_ORDER:
            return
        settings = self._settings_dialog.to_settings()
        assignments = list(settings.channel_assignments)
        while len(assignments) < len(CHANNEL_TAG_ORDER):
            assignments.append(0)
        index = CHANNEL_TAG_ORDER.index(channel_tag)
        role_name = RoleName.coerce(self._control_client.state.selected_role)
        if not self._can_receive_channel(role_name, channel_tag):
            effective_assignments = self._effective_channel_assignments_for_role(assignments, role_name)
            self._apply_channel_labels(effective_assignments)
            if self._control_client.state.connected:
                self._control_client.update_channel_assignments(effective_assignments)
            return
        limit = CHANNEL_LIMITS[channel_tag]
        current = clamp_channel_assignment(channel_tag, assignments[index])
        assignments[index] = clamp_channel_assignment(channel_tag, (current + step) % (limit + 1))
        settings.channel_assignments = assignments
        self._settings_dialog.load_from_settings(settings)
        self._settings_store.save(settings)
        effective_assignments = self._effective_channel_assignments_for_role(assignments, role_name)
        self._control_client.configure(
            callsign=settings.nickname,
            server_address=settings.server_address,
            server_password=settings.server_password,
            channel_assignments=effective_assignments,
        )
        if self._control_client.state.connected:
            self._control_client.update_channel_assignments(effective_assignments)
        self._apply_channel_labels(effective_assignments)

    async def _apply_runtime_settings_after_save(self, settings, previous_settings) -> None:  # noqa: ANN001
        audio_settings = AudioSettings(
            microphone_device_index=settings.microphone_device_index,
            microphone_device_name=settings.microphone_device_name,
            microphone_device_endpoint_id=settings.microphone_device_endpoint_id,
            speaker_device_index=settings.speaker_device_index,
            speaker_device_name=settings.speaker_device_name,
            speaker_device_endpoint_id=settings.speaker_device_endpoint_id,
            microphone_volume_percent=settings.microphone_volume,
            speaker_volume_percent=settings.speaker_volume,
            channel_receive_volumes=settings.channel_receive_volumes,
            channel_pan_modes=settings.channel_pan_modes,
        )
        await asyncio.to_thread(self._audio_runtime.apply_settings, audio_settings)
        await asyncio.to_thread(
            self._soundtrack_service.configure,
            settings.speaker_device_index,
            settings.speaker_device_name,
            settings.speaker_device_endpoint_id,
        )
        if self._audio_started and self._audio_devices_changed(previous_settings, settings):
            await self._audio_runtime.restart_live_streams()

    def _audio_devices_changed(self, previous_settings, settings) -> bool:  # noqa: ANN001
        return (
            previous_settings.microphone_device_index != settings.microphone_device_index
            or previous_settings.microphone_device_name != settings.microphone_device_name
            or previous_settings.microphone_device_endpoint_id != settings.microphone_device_endpoint_id
            or previous_settings.speaker_device_index != settings.speaker_device_index
            or previous_settings.speaker_device_name != settings.speaker_device_name
            or previous_settings.speaker_device_endpoint_id != settings.speaker_device_endpoint_id
        )

    def _bindings_use_joystick(self, channel_bindings: list[str], kneeboard_binding: str) -> bool:
        bindings = [*channel_bindings, kneeboard_binding]
        return any("JOY" in binding.upper() for binding in bindings)

    def _connect_to_server(self) -> None:
        self._save_settings(show_feedback=False)
        settings = self._settings_store.load()
        if settings.nickname.strip().lower() == "user":
            self._show_warning(
                "\uC811\uC18D \uC2E4\uD328",
                "\uC11C\uBC84 \uC811\uC18D\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.\n\n\uC0AC\uC720: \uB2C9\uB124\uC784\uC740 \uAE30\uBCF8\uAC12 'user'\uB85C \uC0AC\uC6A9\uD560 \uC218 \uC5C6\uC2B5\uB2C8\uB2E4.",
            )
            return
        ok, reason = self._async.submit(
            self._control_client.connect_test(
                settings.nickname,
                settings.server_address,
                settings.server_password,
            )
        ).result(timeout=5)
        if not ok:
            self._show_warning(
                "\uC811\uC18D \uC2E4\uD328",
                f"\uC11C\uBC84 \uC811\uC18D\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.\n\n\uC0AC\uC720: {self._friendly_connect_error(reason)}",
            )
            return
        self._ui_sound_player.play("connect")
        self._show_info("\uC811\uC18D \uC131\uACF5", "\uC11C\uBC84 \uC811\uC18D\uC5D0 \uC131\uACF5\uD588\uC2B5\uB2C8\uB2E4.")
        if not self._audio_started:
            self._async.submit(self._audio_runtime.start())
            self._audio_started = True
        self._control_client.connect()

    def _disconnect_from_server(self) -> None:
        self._control_client.disconnect()
        if not self._closing:
            self._ui_sound_player.play("disconnect")
            self._show_info("\uC5F0\uACB0 \uD574\uC81C", "\uC11C\uBC84 \uC5F0\uACB0\uC744 \uD574\uC81C\uD588\uC2B5\uB2C8\uB2E4.")

    def _start_microphone_meter(self) -> None:
        self._ui_sound_player.play("button_click")
        self._async.submit(self._audio_runtime.start_level_meter())

    def _stop_microphone_meter(self) -> None:
        self._ui_sound_player.play("button_click")
        if not self._audio_started and not self._audio_runtime.meter_enabled():
            self._settings_dialog.set_microphone_level(0.0)
            return
        self._async.submit(self._audio_runtime.stop_level_meter())
        self._settings_dialog.set_microphone_level(0.0)

    def _friendly_connect_error(self, reason: str) -> str:
        mapping = {
            "invalid_server_address": "\uC11C\uBC84 \uC8FC\uC18C\uAC00 \uC62C\uBC14\uB974\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.",
            "server_unreachable": "\uC11C\uBC84 \uC8FC\uC18C\uAC00 \uB2E4\uB974\uAC70\uB098 \uC11C\uBC84\uAC00 \uAEBC\uC838 \uC788\uC2B5\uB2C8\uB2E4.",
            "invalid_server_password": "\uC11C\uBC84 \uBE44\uBC00\uBC88\uD638\uAC00 \uC77C\uCE58\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.",
            "client_update_required": "\uC5C5\uB370\uC774\uD2B8\uAC00 \uD544\uC694\uD569\uB2C8\uB2E4. Cloudview Center\uC5D0\uC11C MAYDAY\uB97C \uC5C5\uB370\uC774\uD2B8\uD574 \uC8FC\uC138\uC694.",
            "no_response": "\uC11C\uBC84\uAC00 \uC751\uB2F5\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.",
            "slot_occupied": "\uC774\uBBF8 \uB2E4\uB978 \uC0AC\uC6A9\uC790\uAC00 \uC0AC\uC6A9 \uC911\uC778 \uC2AC\uB86F\uC785\uB2C8\uB2E4.",
            "slot_required": "\uD50C\uB9BF \uD2B8\uB9AC \uC2AC\uB86F\uC5D0 \uBA3C\uC800 \uC811\uC18D\uD574\uC57C \uCC44\uD305/\uBB34\uC804\uC744 \uC0AC\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
        }
        return mapping.get(reason, reason)

    def _set_channel_card_state(self, channel_tag: str, state: ChannelCardState) -> None:
        for widget in self._channel_cards.get(channel_tag, []):
            widget.set_state(state)

    def _sync_control_state(self) -> None:
        online = self._control_client.state.connected
        for label in self._server_value_labels:
            label.setText("온라인" if online else "오프라인")
            label.setObjectName("statusOnline" if online else "statusOffline")
            label.style().unpolish(label)
            label.style().polish(label)
        self._update_kneeboard_editability()
        self._update_main_chat_input_state()
        self._refresh_server_list_panel()

        if self._control_client.state.last_error and self._control_client.state.last_error != self._last_notified_error:
            self._last_notified_error = self._control_client.state.last_error
            if self._control_client.state.last_error == "slot_occupied":
                self._ui_sound_player.play("Soltpull")
                self._show_warning(
                    "\uC2AC\uB86F \uC810\uC720 \uC2E4\uD328",
                    "\uC774\uBBF8 \uB2E4\uB978 \uC0AC\uC6A9\uC790\uAC00 \uC0AC\uC6A9 \uC911\uC778 \uC2AC\uB86F\uC785\uB2C8\uB2E4.",
                )
                self._control_client.clear_last_error()
                self._last_notified_error = ""
            elif self._control_client.state.last_error == "slot_required":
                self._show_warning(
                    "\uC2AC\uB86F \uC811\uC18D \uD544\uC694",
                    "\uD50C\uB9BF \uD2B8\uB9AC \uC2AC\uB86F\uC5D0 \uBA3C\uC800 \uC811\uC18D\uD574\uC57C \uCC44\uD305\uACFC \uBB34\uC804\uC744 \uC0AC\uC6A9\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
                )
                self._control_client.clear_last_error()
                self._last_notified_error = ""

        self._audio_runtime.configure_transport(
            host=self._control_client.state.server_address,
            session_id=self._control_client.state.session_id,
            channel_tag=self._active_channel_tag,
        )
        if not self._control_client.state.connected:
            self._release_active_ptt(notify_server=False)
            self._apply_selected_role(RoleName.SOLDIER.value)
            self._audio_runtime.set_slot_joined(False)
            self._last_confirmed_own_slot_id = ""
            self._update_assignment_panel()
            self._chat_overlay_widget.hide_input()
            self._pending_soundtrack_timer.stop()
            self._pending_video_overlay_timer.stop()
            self._pending_video_overlay_command = None
            self._mission_overlay_widget.hide_now()
            if self._video_overlay_widget is not None:
                self._video_overlay_widget.stop()
            self._kneeboard_overlay_widget.sync_visibility(False)

    def _sync_tree_snapshot(self) -> None:
        model = self._fleet_binding.replace_from_text(self._control_client.state.tree_text)
        if self._control_client.state.presence_entries:
            model = self._fleet_binding.apply_presence(self._control_client.state.presence_entries)
        if self._fleet_tree_widget is not None:
            self._fleet_tree_widget.bind_model(model)
        self._update_assignment_panel(model)

    def _sync_presence_snapshot(self) -> None:
        model = self._fleet_binding.apply_presence(self._control_client.state.presence_entries)
        if self._fleet_tree_widget is not None:
            self._fleet_tree_widget.refresh_presence(model)
        self._update_assignment_panel(model)
        own_session_id = self._control_client.state.session_id
        previous_slot_id = self._last_confirmed_own_slot_id
        own_slot_id = ""
        own_role = ""
        for entry in self._control_client.state.presence_entries:
            if entry.session_id == own_session_id:
                own_slot_id = entry.slot_id
                own_role = entry.role.value
                break
        self._last_confirmed_own_slot_id = own_slot_id
        if own_slot_id != previous_slot_id:
            self._release_active_ptt()
        self._audio_runtime.set_slot_joined(bool(own_slot_id))
        if own_slot_id and own_slot_id != previous_slot_id:
            self._ui_sound_player.play("Slotjoin")
        if own_role and (own_role != self._control_client.state.selected_role or own_slot_id != previous_slot_id):
            self._apply_selected_role(own_role)
        elif not own_slot_id and previous_slot_id:
            self._apply_selected_role(RoleName.SOLDIER.value)

    def _update_assignment_panel(self, model: FleetTreeModel | None = None) -> None:
        if not self._assignment_value_labels and self._squadmate_list is None:
            return
        model = model or self._fleet_binding.model
        own_entry = None
        for entry in self._control_client.state.presence_entries:
            if entry.session_id == self._control_client.state.session_id:
                own_entry = entry
                break
        if own_entry is None:
            self._set_assignment_values("-", "-", "-")
            if self._squadmate_list is not None:
                self._squadmate_list.setHtml("<span style='color:#AAB3D8;'>참가 중인 스쿼드가 없습니다.</span>")
            return

        fleet_name = wing_name = squad_name = "-"
        for fleet in model.fleets:
            if fleet.fleet_id != own_entry.fleet_id:
                continue
            fleet_name = fleet.name
            for wing in fleet.wings:
                if wing.wing_id != own_entry.wing_id:
                    continue
                wing_name = wing.name
                for squad in wing.squads:
                    if squad.squad_id != own_entry.squad_id:
                        continue
                    squad_name = squad.name
                    break
                break
            break

        self._set_assignment_values(fleet_name, wing_name, squad_name)
        squadmates = [
            entry
            for entry in self._control_client.state.presence_entries
            if entry.fleet_id == own_entry.fleet_id
            and entry.wing_id == own_entry.wing_id
            and entry.squad_id == own_entry.squad_id
        ]
        rows = []
        for entry in sorted(squadmates, key=lambda item: (item.session_id != own_entry.session_id, item.callsign.lower())):
            marker = "나" if entry.session_id == own_entry.session_id else entry.role.value.upper()
            color = "#FFFFFF" if entry.session_id == own_entry.session_id else "#AAB3D8"
            rows.append(
                f"<div style='margin-bottom:8px; color:{color};'>"
                f"<b>{html.escape(entry.callsign or '알 수 없음')}</b><br>"
                f"<span style='font-size:8pt;'>{html.escape(marker)}</span>"
                f"</div>"
            )
        if self._squadmate_list is not None:
            self._squadmate_list.setHtml("".join(rows) or "<span style='color:#AAB3D8;'>스쿼드원이 없습니다.</span>")

    def _set_assignment_values(self, fleet: str, wing: str, squad: str) -> None:
        values = {"fleet": fleet, "wing": wing, "squad": squad}
        for key, value in values.items():
            label = self._assignment_value_labels.get(key)
            if label is not None:
                label.setText(value)

    def _join_slot(self, activation: SlotActivation) -> None:
        if not self._control_client.state.connected:
            return
        self._release_active_ptt()
        self._control_client.join_slot(
            fleet_id=activation.fleet_id,
            wing_id=activation.wing_id,
            squad_id=activation.squad_id,
            slot_id=activation.slot_id,
            node_id=activation.node_id,
            role=activation.role,
        )

    def _ensure_admin_authenticated(self) -> bool:
        if self._control_client.state.admin_password == ADMIN_PASSWORD:
            return True
        password, ok = self._prompt_password("관리자 로그인", "관리자 비밀번호를 입력하세요:")
        if not ok:
            return False
        if password != ADMIN_PASSWORD:
            self._show_warning("\uC811\uADFC \uAC70\uBD80", "\uAD00\uB9AC\uC790 \uBE44\uBC00\uBC88\uD638\uAC00 \uC62C\uBC14\uB974\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.")
            return False
        self._control_client.set_admin_password(password)
        self._update_kneeboard_editability()
        return True

    def _prompt_password(self, title: str, label: str) -> tuple[str, bool]:
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.InputMode.TextInput)
        dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
        dialog.setOkButtonText("확인")
        dialog.setCancelButtonText("취소")
        dialog.setStyleSheet(
            """
            QInputDialog {
                background: #101530;
                color: #FFFFFF;
            }
            QLabel {
                color: #FFFFFF;
            }
            QLineEdit {
                background: #1F264B;
                color: #FFFFFF;
                border: 1px solid rgba(154, 167, 232, 130);
                border-radius: 8px;
                padding: 7px 9px;
                selection-background-color: #4F7BFF;
            }
            QPushButton {
                background: #263056;
                color: #FFFFFF;
                border: 1px solid rgba(154, 167, 232, 110);
                border-radius: 8px;
                min-width: 74px;
                min-height: 30px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #4F7BFF;
            }
            """
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.textValue(), accepted

    def _open_admin_dialog(self) -> None:
        if not self._ensure_admin_authenticated():
            return
        self._prepare_fleet_settings()
        self._admin_dialog.set_embedded_mode(False)
        self._admin_dialog.show()
        self._admin_dialog.raise_()
        self._admin_dialog.activateWindow()

    def _prepare_fleet_settings(self) -> None:
        tree_text = self._control_client.state.tree_text
        if not tree_text.strip():
            tree_text = encode_fleet_tree(self._fleet_binding.model)
        self._admin_dialog.set_tree_text(tree_text)

    def _save_tree_text(self, tree_text: str) -> None:
        if not tree_text.strip():
            self._admin_dialog.set_status("플릿 트리 JSON은 비워둘 수 없습니다.", ok=False)
            return
        try:
            model = decode_fleet_tree(tree_text)
            model = ensure_unique_tree_ids(model)
            normalized = encode_fleet_tree(model)
        except Exception as exc:
            self._admin_dialog.set_status(f"플릿 트리 JSON 오류: {exc}", ok=False)
            return
        self._control_client.update_tree(normalized)
        model = self._fleet_binding.replace_from_text(normalized)
        if self._fleet_tree_widget is not None:
            self._fleet_tree_widget.bind_model(model)
        self._admin_dialog.set_tree_text(normalized)
        self._admin_dialog.set_status("플릿 트리를 서버에 저장했습니다.", ok=True)

    def _set_active_channel(self, channel_tag: str) -> None:
        self._active_channel_tag = channel_tag
        self._audio_runtime.set_channel_tag(channel_tag)
        for key, state in self._channel_states.items():
            state.active = key == channel_tag
            self._set_channel_card_state(key, state)

    def _release_active_ptt(self, *, notify_server: bool = True) -> None:
        if self._active_binding_channel is None and self._active_ptt_key is None:
            return
        current_channel = self._active_binding_channel or self._active_channel_tag
        self._active_binding_channel = None
        self._active_ptt_key = None
        self._binding_release_deadline = 0.0
        if notify_server and self._control_client.state.connected:
            self._control_client.set_ptt_state(False, current_channel)
        self._async.submit(self._audio_runtime.stop_transmit())

    def _apply_selected_role(self, role: str) -> None:
        role_name = RoleName.coerce(role)
        self._control_client.state.selected_role = role_name.value
        self._audio_runtime.set_selected_role(role_name.value)
        permissions = ROLE_PERMISSIONS[role_name]
        for channel_tag, state in self._channel_states.items():
            channel_key = CHANNEL_KEY_BY_TAG[channel_tag]
            permission = permissions.channel(channel_key)
            state.enabled = self._has_active_slot() and (permission.tx or permission.rx)
            self._set_channel_card_state(channel_tag, state)
        settings = self._settings_store.load()
        effective_assignments = self._effective_channel_assignments_for_role(settings.channel_assignments, role_name)
        self._control_client.configure(
            callsign=settings.nickname,
            server_address=settings.server_address,
            server_password=settings.server_password,
            channel_assignments=effective_assignments,
        )
        if self._control_client.state.connected:
            self._control_client.update_channel_assignments(effective_assignments)
        self._apply_channel_labels(effective_assignments)
        active_key = CHANNEL_KEY_BY_TAG.get(self._active_channel_tag)
        if active_key is not None:
            active_permission = permissions.channel(active_key)
            if not active_permission.tx and not active_permission.rx:
                self._set_active_channel("general")

    def _can_transmit(self, channel_tag: str) -> bool:
        if not self._control_client.state.connected or not self._has_active_slot():
            return False
        role_name = RoleName.coerce(self._control_client.state.selected_role)
        channel_key = CHANNEL_KEY_BY_TAG.get(channel_tag)
        if channel_key is None:
            return True
        return ROLE_PERMISSIONS[role_name].channel(channel_key).tx

    def _can_receive_channel(self, role_name: RoleName, channel_tag: str) -> bool:
        channel_key = CHANNEL_KEY_BY_TAG.get(channel_tag)
        if channel_key is None:
            return True
        return ROLE_PERMISSIONS[role_name].channel(channel_key).rx

    def _effective_channel_assignments_for_role(
        self,
        channel_assignments: list[int],
        role: str | RoleName,
    ) -> list[int]:
        role_name = RoleName.coerce(role)
        effective: list[int] = []
        for index, channel_tag in enumerate(CHANNEL_TAG_ORDER):
            value = (
                int(channel_assignments[index])
                if index < len(channel_assignments)
                else DEFAULT_CHANNEL_ASSIGNMENTS[index]
            )
            if not self._can_receive_channel(role_name, channel_tag):
                value = 0
            effective.append(clamp_channel_assignment(channel_tag, value))
        return effective

    def _has_active_slot(self) -> bool:
        return bool(self._last_confirmed_own_slot_id)

    def _tick_realtime_ui(self) -> None:
        self._star_citizen_detected = self._process_detection.detected
        self._settings_dialog.set_microphone_level(self._audio_runtime.state.microphone_level)
        self._poll_chat_hotkey()
        self._poll_kneeboard_hotkey()
        self._tick_input_ptt()
        self._sync_overlay()
        self._sync_chat_overlay()
        self._sync_kneeboard_overlay()

    def _tick_input_ptt(self) -> None:
        if self._chat_overlay_widget.has_active_input():
            self._release_active_ptt()
            return
        if not self._control_client.state.connected or not self._has_active_slot():
            self._release_active_ptt(notify_server=self._control_client.state.connected)
            return
        matched_channel = None
        for index, binding in enumerate(self._channel_bindings[:4]):
            if binding and self._input_monitor.is_binding_pressed(binding):
                channel_tag = CHANNEL_TAG_ORDER[index]
                if self._can_transmit(channel_tag):
                    matched_channel = channel_tag
                    break
        if matched_channel is not None and self._active_binding_channel is None and self._active_ptt_key is None:
            self._active_binding_channel = matched_channel
            self._binding_release_deadline = time.monotonic() + self._binding_release_grace_seconds
            self._set_active_channel(matched_channel)
            self._control_client.set_ptt_state(True, matched_channel)
            self._async.submit(self._audio_runtime.start_transmit())
        elif matched_channel is not None and self._active_binding_channel is not None:
            self._binding_release_deadline = time.monotonic() + self._binding_release_grace_seconds
        elif matched_channel is None and self._active_binding_channel is not None:
            if time.monotonic() < self._binding_release_deadline:
                return
            current_channel = self._active_binding_channel
            self._active_binding_channel = None
            self._binding_release_deadline = 0.0
            self._control_client.set_ptt_state(False, current_channel)
            self._async.submit(self._audio_runtime.stop_transmit())

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return
        if self._chat_overlay_widget.has_active_input():
            super().keyPressEvent(event)
            return
        if (
            event.key() == Qt.Key.Key_Slash
            and self._control_client.state.connected
            and self._star_citizen_detected
            and self._has_active_slot()
        ):
            self._open_chat_input()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.isAutoRepeat():
            super().keyReleaseEvent(event)
            return
        if self._active_ptt_key is None or event.key() != self._active_ptt_key:
            super().keyReleaseEvent(event)
            return
        self._release_active_ptt()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._sync_background_image()

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self._sync_background_image()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        if self._closing:
            super().closeEvent(event)
            return
        self._closing = True
        self._persist_dialog_settings_on_exit()
        self._settings_dialog.close()
        self._admin_dialog.close()
        if self._fleet_tree_dialog is not None:
            self._fleet_tree_dialog.close()
        self._notice_dialog.close()
        self._overlay_widget.close()
        self._chat_overlay_widget.close()
        self._mission_overlay_widget.close()
        if self._video_overlay_widget is not None:
            self._video_overlay_widget.stop()
            self._video_overlay_widget.close()
        self._kneeboard_overlay_widget.close()
        self._pending_soundtrack_timer.stop()
        self._pending_video_overlay_timer.stop()
        self._kneeboard_update_timer.stop()
        self._soundtrack_service.close()
        self._input_monitor.stop()
        self._process_detection.stop()
        self._server_discovery.stop()
        self._control_client.close()
        if self._audio_started or self._audio_runtime.meter_enabled():
            self._async.submit(self._audio_runtime.stop()).result(timeout=5)
        self._async.close()
        for widget in QApplication.topLevelWidgets():
            if widget is not self:
                widget.close()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _persist_dialog_settings_on_exit(self) -> None:
        if not self._device_list_loaded:
            return
        try:
            self._settings_store.save(self._settings_dialog.to_settings())
        except Exception:
            return

    def _play_exit_sound(self) -> None:
        return

    def _apply_binding_labels(self, bindings: list[str]) -> None:
        for index, channel_tag in enumerate(CHANNEL_TAG_ORDER):
            state = self._channel_states.get(channel_tag)
            if state is None:
                continue
            state.binding = bindings[index] if index < len(bindings) else state.binding
            self._set_channel_card_state(channel_tag, state)

    def _apply_channel_labels(self, channel_assignments: list[int]) -> None:
        for index, channel_tag in enumerate(CHANNEL_TAG_ORDER):
            state = self._channel_states.get(channel_tag)
            if state is None:
                continue
            state.channel_number = (
                int(channel_assignments[index])
                if index < len(channel_assignments)
                else DEFAULT_CHANNEL_ASSIGNMENTS[index]
            )
            self._set_channel_card_state(channel_tag, state)

    def _show_info(self, title: str, text: str) -> None:
        self._show_message(title, text)

    def _show_warning(self, title: str, text: str) -> None:
        self._show_message(title, text)

    def _show_message(self, title: str, text: str) -> None:
        parent = self._settings_dialog if self._settings_dialog.isVisible() else self
        dialog = AppMessageDialog(title, text, parent)
        dialog.exec()

    def _sync_overlay(self) -> None:
        if not self._star_citizen_detected:
            self._overlay_widget.set_talkers([])
            self._mission_overlay_widget.hide_now()
            return
        talkers: list[OverlayTalker] = []
        own_talker = self._own_transmitting_overlay_talker()
        if own_talker is not None:
            talkers.append(own_talker)
        heard_talkers = self._audio_runtime.current_heard_talkers()
        if not heard_talkers and not talkers:
            self._overlay_widget.set_talkers([])
            return
        by_session = {entry.session_id: entry for entry in self._control_client.state.presence_entries}
        for session_id, channel_tag in heard_talkers:
            entry = by_session.get(session_id)
            if entry is None or not entry.callsign:
                continue
            if session_id == self._control_client.state.session_id:
                continue
            talkers.append(OverlayTalker(channel=channel_tag, callsign=entry.callsign))
        self._overlay_widget.set_talkers(talkers)

    def _own_transmitting_overlay_talker(self) -> OverlayTalker | None:
        if not self._audio_runtime.state.transmitting or not self._has_active_slot():
            return None
        callsign = self._control_client.state.callsign.strip() or "YOU"
        for entry in self._control_client.state.presence_entries:
            if entry.session_id == self._control_client.state.session_id and entry.callsign:
                callsign = entry.callsign
                break
        return OverlayTalker(channel=self._active_channel_tag, callsign=callsign, is_self=True)

    def _sync_chat_overlay(self) -> None:
        latest_message = self._control_client.state.chat_entries[-1] if self._control_client.state.chat_entries else None
        if latest_message is None:
            self._last_chat_message_signature = None
        else:
            signature = (
                len(self._control_client.state.chat_entries),
                latest_message.session_id,
                latest_message.text,
            )
            if signature != self._last_chat_message_signature:
                self._last_chat_message_signature = signature
                if latest_message.session_id != self._control_client.state.session_id:
                    self._ui_sound_player.play("chat_tick")
        if self._main_chat_history is not None:
            self._main_chat_history.setHtml(self._format_chat_entries_html())
            self._main_chat_history.verticalScrollBar().setValue(self._main_chat_history.verticalScrollBar().maximum())
        self._update_main_chat_input_state()
        if not self._star_citizen_detected or not self._control_client.state.connected:
            self._chat_overlay_widget.hide_input()
            self._chat_overlay_widget.set_messages([])
            return
        self._chat_overlay_widget.set_messages(self._control_client.state.chat_entries)

    def _poll_chat_hotkey(self) -> None:
        snapshot = self._input_monitor.snapshot()
        slash_pressed = "/" in snapshot
        if (
            slash_pressed
            and not self._chat_hotkey_latched
            and self._control_client.state.connected
            and self._star_citizen_detected
            and not self._chat_overlay_widget.has_active_input()
        ):
            self._open_chat_input()
        self._chat_hotkey_latched = slash_pressed

    def _poll_kneeboard_hotkey(self) -> None:
        if not self._kneeboard_binding:
            self._kneeboard_hotkey_latched = False
            return
        if self._chat_overlay_widget.has_active_input():
            return
        if self._main_chat_input is not None and self._main_chat_input.hasFocus():
            return
        if self._kneeboard_editor is not None and self._kneeboard_editor.hasFocus():
            return
        pressed = self._input_monitor.is_binding_pressed(self._kneeboard_binding)
        if pressed and not self._kneeboard_hotkey_latched:
            self._kneeboard_overlay_enabled = not self._kneeboard_overlay_enabled
        self._kneeboard_hotkey_latched = pressed

    def _sync_kneeboard_overlay(self) -> None:
        should_show = (
            self._kneeboard_overlay_enabled
            and self._control_client.state.connected
            and self._star_citizen_detected
        )
        self._kneeboard_overlay_widget.sync_visibility(should_show)

    def _open_chat_input(self) -> None:
        if not self._control_client.state.connected or not self._star_citizen_detected:
            return
        if self._chat_overlay_widget.has_active_input():
            return
        self._chat_previous_foreground_hwnd = self._foreground_window_handle()
        self._chat_overlay_widget.show_input()
        QTimer.singleShot(0, self._activate_chat_overlay_window)

    def _submit_chat_message(self, text: str) -> None:
        if not self._control_client.state.connected:
            return
        if self._handle_admin_chat_command(text):
            return
        self._control_client.send_chat(text)

    def _submit_main_chat_message(self) -> None:
        if self._main_chat_input is None:
            return
        text = self._main_chat_input.text().strip()
        if not text:
            return
        self._submit_chat_message(text)
        self._main_chat_input.clear()

    def _request_kneeboard_admin_edit(self) -> None:
        if not self._ensure_admin_authenticated():
            return
        self._update_kneeboard_editability()
        if self._kneeboard_editor is not None:
            self._kneeboard_editor.setFocus()

    def _on_kneeboard_text_changed(self) -> None:
        if self._suppress_kneeboard_edit_signal:
            return
        if self._control_client.state.admin_password != ADMIN_PASSWORD:
            return
        self._kneeboard_update_timer.start(350)
        if self._kneeboard_status_label is not None:
            self._kneeboard_status_label.setText("동기화 중...")

    def _commit_kneeboard_update(self) -> None:
        if self._kneeboard_editor is None:
            return
        if self._control_client.state.admin_password != ADMIN_PASSWORD:
            return
        self._control_client.send_kneeboard_update(self._kneeboard_editor.toPlainText())
        if self._kneeboard_status_label is not None:
            self._kneeboard_status_label.setText("편집 가능")

    def _sync_kneeboard_text(self) -> None:
        text = self._control_client.state.kneeboard_text
        if self._kneeboard_editor is not None and self._kneeboard_editor.toPlainText() != text:
            self._suppress_kneeboard_edit_signal = True
            self._kneeboard_editor.setPlainText(text)
            self._suppress_kneeboard_edit_signal = False
        self._kneeboard_overlay_widget.set_text(text)
        self._update_kneeboard_editability()

    def _update_kneeboard_editability(self) -> None:
        editor = self._kneeboard_editor
        if editor is None:
            return
        is_admin = self._control_client.state.admin_password == ADMIN_PASSWORD
        editor.setReadOnly(not is_admin)
        if self._kneeboard_admin_button is not None:
            self._kneeboard_admin_button.setText("실시간 편집" if is_admin else "관리자 편집")
        if self._kneeboard_status_label is not None:
            self._kneeboard_status_label.setText("편집 가능" if is_admin else "읽기 전용")

    def _update_main_chat_input_state(self) -> None:
        enabled = self._control_client.state.connected
        if self._main_chat_input is not None:
            self._main_chat_input.setEnabled(enabled)
        if self._main_chat_send_button is not None:
            self._main_chat_send_button.setEnabled(enabled)

    def _format_chat_entries_html(self) -> str:
        if not self._control_client.state.chat_entries:
            return ""
        lines: list[str] = []
        for message in self._control_client.state.chat_entries[-20:]:
            callsign = html.escape(message.callsign or "알 수 없음")
            text = html.escape(message.text)
            role_color = self._chat_role_color(message.role)
            lines.append(
                (
                    "<div style='margin: 0 0 6px 0;'>"
                    f"<span style='color: {role_color}; font-weight: 700;'>{callsign}</span>"
                    f"<span style='color: #dce6ee;'> : {text}</span>"
                    "</div>"
                )
            )
        return "".join(lines)

    def _chat_role_color(self, role: str) -> str:
        role_map = {
            RoleName.COMMANDER.value: "#f4c65f",
            RoleName.OFFICER.value: "#6fc7ff",
            RoleName.PILOT.value: "#71d98f",
            RoleName.SOLDIER.value: "#dce6ee",
            "Sergeant": "#71d98f",
        }
        return role_map.get(role, "#b6c2cd")

    def _refresh_soundtrack_tracks(self) -> None:
        tracks = self._soundtrack_service.refresh_library()
        if self._soundtrack_list is None:
            return
        current_text = self._soundtrack_track_edit.text().strip() if self._soundtrack_track_edit is not None else ""
        self._soundtrack_list.clear()
        self._soundtrack_list.addItems(tracks)
        if current_text:
            for row in range(self._soundtrack_list.count()):
                item = self._soundtrack_list.item(row)
                if item is not None and item.text() == current_text:
                    self._soundtrack_list.setCurrentRow(row)
                    break

    def _refresh_video_tracks(self) -> None:
        tracks = self._video_overlay_service.refresh_library()
        if self._video_list is None:
            return
        current_text = self._video_track_edit.text().strip() if self._video_track_edit is not None else ""
        self._video_list.clear()
        self._video_list.addItems(tracks)
        if current_text:
            for row in range(self._video_list.count()):
                item = self._video_list.item(row)
                if item is not None and item.text() == current_text:
                    self._video_list.setCurrentRow(row)
                    break

    def _sync_soundtrack_selection(self) -> None:
        if self._soundtrack_list is None or self._soundtrack_track_edit is None:
            return
        item = self._soundtrack_list.currentItem()
        if item is not None:
            self._soundtrack_track_edit.setText(item.text())

    def _sync_video_selection(self) -> None:
        if self._video_list is None or self._video_track_edit is None:
            return
        item = self._video_list.currentItem()
        if item is not None:
            self._video_track_edit.setText(item.text())

    def _set_admin_media_status(self, message: str, ok: bool = True) -> None:
        if self._admin_media_status_label is None:
            return
        self._admin_media_status_label.setText(message)
        self._admin_media_status_label.setStyleSheet(f"color: {'#AAB3D8' if ok else '#ff9ba8'};")

    def _emit_soundtrack_play(self) -> None:
        if self._soundtrack_track_edit is None or self._soundtrack_volume_edit is None or self._soundtrack_fade_edit is None:
            return
        track_id = self._soundtrack_track_edit.text().strip()
        if not track_id:
            self._set_admin_media_status("먼저 사운드트랙을 선택하거나 입력하세요.", ok=False)
            return
        try:
            volume_percent = int(self._soundtrack_volume_edit.text().strip() or "10")
            fade_ms = int(self._soundtrack_fade_edit.text().strip() or "1200")
        except ValueError:
            self._set_admin_media_status("사운드트랙 볼륨과 페이드는 숫자로 입력하세요.", ok=False)
            return
        self._request_soundtrack_play(track_id, volume_percent, fade_ms)

    def _emit_soundtrack_stop(self) -> None:
        if self._soundtrack_fade_edit is None:
            return
        try:
            fade_ms = int(self._soundtrack_fade_edit.text().strip() or "600")
        except ValueError:
            self._set_admin_media_status("사운드트랙 페이드는 숫자로 입력하세요.", ok=False)
            return
        self._request_soundtrack_stop(fade_ms)

    def _emit_video_overlay_play(self) -> None:
        if self._video_track_edit is None or self._video_volume_edit is None:
            return
        video_id = self._video_track_edit.text().strip()
        if not video_id:
            self._set_admin_media_status("먼저 영상을 선택하거나 입력하세요.", ok=False)
            return
        try:
            volume_percent = int(self._video_volume_edit.text().strip() or "10")
        except ValueError:
            self._set_admin_media_status("영상 볼륨은 숫자로 입력하세요.", ok=False)
            return
        self._request_video_overlay_play(video_id, max(0, min(100, volume_percent)))

    def _emit_video_overlay_stop(self) -> None:
        self._request_video_overlay_stop()

    def _request_soundtrack_play(self, track_id: str, volume_percent: int, fade_ms: int) -> None:
        if not self._control_client.state.connected:
            self._set_admin_media_status("사운드트랙 명령을 보내려면 먼저 서버에 접속하세요.", ok=False)
            self._show_warning(
                "\uC7AC\uC0DD \uC2E4\uD328",
                "\uC11C\uBC84\uC5D0 \uC5F0\uACB0\uB41C \uC0C1\uD0DC\uC5D0\uC11C\uB9CC OST \uC7AC\uC0DD\uC744 \uC9C0\uC2DC\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
            )
            return
        self._control_client.send_soundtrack_play(track_id, volume_percent, fade_ms)
        self._set_admin_media_status(f"사운드트랙 재생 요청: {track_id}")

    def _request_soundtrack_stop(self, fade_ms: int) -> None:
        if not self._control_client.state.connected:
            self._set_admin_media_status("사운드트랙 명령을 보내려면 먼저 서버에 접속하세요.", ok=False)
            self._show_warning(
                "\uC815\uC9C0 \uC2E4\uD328",
                "\uC11C\uBC84\uC5D0 \uC5F0\uACB0\uB41C \uC0C1\uD0DC\uC5D0\uC11C\uB9CC OST \uC815\uC9C0\uB97C \uC9C0\uC2DC\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
            )
            return
        self._control_client.send_soundtrack_stop(fade_ms)
        self._set_admin_media_status("사운드트랙 정지 요청 완료.")

    def _request_video_overlay_play(self, video_id: str, volume_percent: int) -> None:
        if not self._control_client.state.connected:
            self._set_admin_media_status("영상 명령을 보내려면 먼저 서버에 접속하세요.", ok=False)
            self._show_warning(
                "\uC7AC\uC0DD \uC2E4\uD328",
                "\uC11C\uBC84\uC5D0 \uC5F0\uACB0\uB41C \uC0C1\uD0DC\uC5D0\uC11C\uB9CC \uC601\uC0C1 \uC624\uBC84\uB808\uC774 \uC7AC\uC0DD\uC744 \uC9C0\uC2DC\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
            )
            return
        self._control_client.send_video_overlay_play(video_id, volume_percent)
        self._set_admin_media_status(f"영상 오버레이 재생 요청: {video_id}")

    def _request_video_overlay_stop(self) -> None:
        if not self._control_client.state.connected:
            self._set_admin_media_status("영상 명령을 보내려면 먼저 서버에 접속하세요.", ok=False)
            self._show_warning(
                "\uC815\uC9C0 \uC2E4\uD328",
                "\uC11C\uBC84\uC5D0 \uC5F0\uACB0\uB41C \uC0C1\uD0DC\uC5D0\uC11C\uB9CC \uC601\uC0C1 \uC624\uBC84\uB808\uC774 \uC815\uC9C0\uB97C \uC9C0\uC2DC\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4.",
            )
            return
        self._control_client.send_video_overlay_stop()
        self._set_admin_media_status("영상 오버레이 정지 요청 완료.")

    def _handle_soundtrack_command(self, command: dict) -> None:
        action = str(command.get("action", "")).strip().lower()
        self._pending_soundtrack_timer.stop()
        if action == "stop":
            self._pending_soundtrack_command = None
            self._soundtrack_service.stop(int(command.get("fade_ms", 600)))
            return
        if action != "play":
            return
        self._pending_soundtrack_command = dict(command)
        delay_ms = self._media_command_delay_ms(command)
        if delay_ms > 0:
            self._soundtrack_service.prepare(
                str(command.get("track_id", "")),
                int(command.get("volume_percent", 10)),
            )
        if delay_ms <= 0:
            self._play_pending_soundtrack()
            return
        self._pending_soundtrack_timer.start(delay_ms)

    def _play_pending_soundtrack(self) -> None:
        command = self._pending_soundtrack_command
        self._pending_soundtrack_command = None
        if command is None:
            return
        volume_percent = int(command.get("volume_percent", 10))
        fade_ms = int(command.get("fade_ms", 1200))
        if not self._soundtrack_service.play_prepared(volume_percent=volume_percent, fade_ms=fade_ms):
            self._soundtrack_service.play(str(command.get("track_id", "")), volume_percent, fade_ms)

    def _handle_mission_overlay_command(self, command: dict) -> None:
        if not self._star_citizen_detected:
            self._mission_overlay_widget.hide_now()
            return
        self._mission_overlay_widget.show_message(
            str(command.get("text", "")),
            duration_ms=int(command.get("duration_ms", 3600)),
            fade_ms=int(command.get("fade_ms", 450)),
            color=str(command.get("color", "white")),
            font_scale=float(command.get("font_scale", 1.0)),
        )

    def _handle_video_overlay_command(self, command: dict) -> None:
        action = str(command.get("action", "")).strip().lower()
        self._pending_video_overlay_timer.stop()
        if action == "stop":
            self._pending_video_overlay_command = None
            if self._video_overlay_widget is not None:
                self._video_overlay_widget.stop()
            return
        if action != "play":
            return
        self._pending_video_overlay_command = dict(command)
        video_path = self._video_overlay_service.resolve_video(str(command.get("video_id", "")))
        delay_ms = self._media_command_delay_ms(command)
        if delay_ms > 0 and video_path is not None:
            self._video_overlay().prepare_file(
                str(video_path),
                volume_percent=int(command.get("volume_percent", 10)),
            )
        if delay_ms <= 0:
            self._play_pending_video_overlay()
            return
        self._pending_video_overlay_timer.start(delay_ms)

    def _play_pending_video_overlay(self) -> None:
        command = self._pending_video_overlay_command
        self._pending_video_overlay_command = None
        if command is None:
            return
        video_overlay = self._video_overlay()
        if video_overlay.play_prepared():
            return
        video_path = self._video_overlay_service.resolve_video(str(command.get("video_id", "")))
        if video_path is None:
            video_overlay.stop()
            return
        video_overlay.play_file(str(video_path), volume_percent=int(command.get("volume_percent", 10)))

    def _video_overlay(self) -> VideoOverlayWidget:
        if self._video_overlay_widget is None:
            self._video_overlay_widget = VideoOverlayWidget()
        return self._video_overlay_widget

    def _media_command_delay_ms(self, command: dict) -> int:
        if "start_delay_ms" in command:
            return max(0, int(command.get("start_delay_ms", 0) or 0))
        start_at_ms = int(command.get("start_at_ms", 0) or 0)
        return max(0, start_at_ms - int(time.time() * 1000))

    def _handle_admin_chat_command(self, text: str) -> bool:
        if self._control_client.state.admin_password != ADMIN_PASSWORD:
            return False
        command = parse_admin_chat_command(text)
        if command is None:
            return False
        if not self._control_client.state.connected:
            return True
        self._dispatch_admin_chat_command(command)
        return True

    def _dispatch_admin_chat_command(self, command: AdminChatCommand) -> None:
        if command.kind == "soundtrack_play":
            self._control_client.send_soundtrack_play(command.track_id, command.volume_percent, command.fade_ms)
            return
        if command.kind == "soundtrack_stop":
            self._control_client.send_soundtrack_stop(command.fade_ms)
            return
        if command.kind == "mission_overlay":
            self._control_client.send_mission_overlay(
                command.text,
                command.duration_ms,
                command.fade_ms,
                color=command.color,
                font_scale=command.font_scale,
            )
            return
        if command.kind == "video_overlay_play":
            self._control_client.send_video_overlay_play(command.video_id, command.volume_percent)
            return
        if command.kind == "video_overlay_stop":
            self._control_client.send_video_overlay_stop()
            return
        if command.kind == "notice_update":
            self._control_client.send_notice_update(command.notice_text)

    def _activate_chat_overlay_window(self) -> None:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self._chat_overlay_widget.winId())
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
            current_thread = kernel32.GetCurrentThreadId()
            attached = False
            if foreground_thread and foreground_thread != current_thread:
                attached = bool(user32.AttachThreadInput(foreground_thread, current_thread, True))
            try:
                user32.ShowWindow(hwnd, 5)
                user32.BringWindowToTop(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(foreground_thread, current_thread, False)
        except Exception:
            pass
        self._chat_overlay_widget.focus_input()

    def _restore_previous_foreground_window(self) -> None:
        hwnd = self._chat_previous_foreground_hwnd
        self._chat_previous_foreground_hwnd = None
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            if user32.IsWindow(hwnd):
                user32.SetForegroundWindow(hwnd)
        except Exception:
            return

    def _foreground_window_handle(self) -> int | None:
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None
        return int(hwnd) if hwnd else None

    def _stylesheet(self) -> str:
        return """
        QMainWindow {
            background: transparent;
        }
        QWidget#appShell {
            background: rgba(20, 27, 52, 255);
        }
        QLabel#backgroundImage {
            background: transparent;
        }
        QWidget#contentSurface {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(20, 27, 52, 216), stop:0.46 rgba(20, 27, 52, 178), stop:0.52 rgba(79, 123, 255, 18), stop:1 rgba(20, 27, 52, 126));
        }
        QFrame#sideRail {
            background: rgba(27, 34, 68, 232);
            border-right: 1px solid rgba(125, 139, 205, 66);
        }
        QPushButton#sideBrandButton {
            background: rgba(79, 123, 255, 116);
            color: #FFFFFF;
            border: 1px solid rgba(154, 167, 232, 118);
            border-radius: 8px;
            min-width: 38px;
            max-width: 38px;
            min-height: 34px;
            max-height: 34px;
            padding: 0;
        }
        QPushButton#sideBrandButton:hover {
            background: rgba(79, 123, 255, 132);
            border: 1px solid rgba(154, 167, 232, 128);
        }
        QPushButton#sideBrandButton[selected="true"] {
            background: rgba(79, 123, 255, 156);
            border: 1px solid rgba(154, 167, 232, 154);
        }
        QPushButton#sideNavButton {
            background: transparent;
            color: #FFFFFF;
            border: 1px solid transparent;
            border-radius: 8px;
            min-width: 38px;
            max-width: 38px;
            min-height: 34px;
            max-height: 34px;
            padding: 0;
        }
        QPushButton#sideNavButton:hover {
            background: rgba(79, 123, 255, 132);
            border: 1px solid rgba(154, 167, 232, 128);
            color: #FFFFFF;
        }
        QPushButton#sideNavButton[selected="true"] {
            background: rgba(79, 123, 255, 156);
            border: 1px solid rgba(154, 167, 232, 154);
            color: #FFFFFF;
        }
        QWidget#contentPage {
            background: transparent;
        }
        QFrame#headerFrame {
            background: transparent;
            border: none;
        }
        QFrame#panel {
            background: rgba(48, 56, 100, 202);
            border: 1px solid rgba(125, 139, 205, 72);
            border-radius: 8px;
        }
        QFrame#heroPanel {
            background: rgba(31, 38, 75, 194);
            border: 1px solid rgba(125, 139, 205, 84);
            border-radius: 8px;
        }
        QFrame#imageStagePanel {
            background: rgba(48, 56, 100, 158);
            border: 1px solid rgba(125, 139, 205, 70);
            border-radius: 8px;
        }
        QFrame#imageDropZone {
            background: rgba(31, 38, 75, 92);
            border: 1px solid rgba(154, 167, 232, 86);
            border-radius: 8px;
        }
        QLabel#visualStageImage {
            background: transparent;
            border-radius: 8px;
        }
        QFrame#subPanel {
            background: rgba(43, 51, 94, 178);
            border: 1px solid rgba(125, 139, 205, 52);
            border-radius: 8px;
        }
        QFrame#serverEntry {
            background: rgba(31, 38, 75, 150);
            border: 1px solid rgba(125, 139, 205, 52);
            border-radius: 8px;
        }
        QLabel {
            color: #FFFFFF;
        }
        QLabel#heroTitle {
            color: #FFFFFF;
        }
        QLabel#subtitle {
            color: #AAB3D8;
        }
        QLabel#mutedText {
            color: #AAB3D8;
        }
        QLabel#imageStageText {
            color: rgba(154, 167, 232, 190);
        }
        QLabel#versionLabel {
            color: rgba(170, 179, 216, 210);
            background: transparent;
            border: none;
            padding: 0;
        }
        QLabel#statusOnline {
            color: #AAB3D8;
        }
        QLabel#statusOffline {
            color: #AAB3D8;
        }
        QLabel#kneeboardStatus {
            color: #AAB3D8;
        }
        QLabel#statusPill {
            color: #FFFFFF;
            background: rgba(79, 123, 255, 80);
            border: 1px solid rgba(154, 167, 232, 72);
            border-radius: 8px;
            padding: 5px 8px;
        }
        QLabel#assignmentValue {
            color: #FFFFFF;
            background: rgba(31, 38, 75, 150);
            border: 1px solid rgba(125, 139, 205, 50);
            border-radius: 7px;
            padding: 0 8px;
        }
        QPushButton {
            background: rgba(38, 46, 86, 218);
            color: #FFFFFF;
            border: 1px solid rgba(125, 139, 205, 70);
            border-radius: 8px;
            min-width: 36px;
            min-height: 30px;
            padding: 0 10px;
        }
        QPushButton:hover {
            background: rgba(79, 123, 255, 116);
            border: 1px solid rgba(154, 167, 232, 148);
        }
        QPushButton#primaryButton {
            background: #4F7BFF;
            color: #FFFFFF;
            border: 1px solid rgba(154, 167, 232, 128);
            min-height: 36px;
        }
        QPushButton#primaryButton:hover {
            background: #6D8EFF;
        }
        QPushButton#joinServerButton {
            background: rgba(79, 123, 255, 132);
            border: 1px solid rgba(154, 167, 232, 98);
            min-height: 28px;
        }
        QPushButton#joinServerButton:hover {
            background: rgba(79, 123, 255, 190);
        }
        QPushButton#disconnectServerButton {
            background: transparent;
            border: 1px solid rgba(125, 139, 205, 52);
            color: #FFFFFF;
            min-height: 26px;
            padding: 0 8px;
        }
        QPushButton#disconnectServerButton:hover {
            background: rgba(255, 60, 172, 70);
            border: 1px solid rgba(255, 60, 172, 110);
        }
        QPushButton#nicknameDisplayButton {
            background: rgba(31, 38, 75, 142);
            border: 1px solid rgba(125, 139, 205, 52);
            color: #FFFFFF;
            text-align: left;
            min-height: 30px;
            padding: 0 10px;
        }
        QPushButton#nicknameDisplayButton:hover {
            background: rgba(79, 123, 255, 90);
            border: 1px solid rgba(154, 167, 232, 110);
        }
        QPushButton#nicknameSaveButton {
            background: rgba(79, 123, 255, 142);
            border: 1px solid rgba(154, 167, 232, 110);
            min-width: 58px;
            min-height: 30px;
            padding: 0 8px;
        }
        QPushButton#settingsNavButton {
            background: rgba(31, 38, 75, 150);
            border: 1px solid rgba(125, 139, 205, 52);
            color: #FFFFFF;
            min-height: 34px;
            text-align: left;
            padding-left: 12px;
        }
        QPushButton#settingsNavButton:hover {
            background: rgba(79, 123, 255, 108);
        }
        QPushButton#settingsNavButton[selected="true"] {
            background: rgba(79, 123, 255, 156);
            border: 1px solid rgba(154, 167, 232, 142);
        }
        QPushButton#roundToolButton {
            border-radius: 12px;
            min-width: 30px;
            max-width: 30px;
            min-height: 28px;
            max-height: 28px;
            padding: 0;
        }
        QPushButton#topCloseButton {
            background: transparent;
            color: rgba(170, 179, 216, 190);
            border: none;
            border-radius: 0;
            min-width: 18px;
            max-width: 18px;
            min-height: 18px;
            max-height: 18px;
            padding: 0;
        }
        QPushButton#topCloseButton:hover {
            background: transparent;
            border: none;
            color: #FFFFFF;
        }
        QLineEdit, QTextBrowser, QPlainTextEdit, QListWidget {
            background: rgba(48, 56, 100, 202);
            color: #FFFFFF;
            border: 1px solid rgba(125, 139, 205, 52);
            border-radius: 8px;
            padding: 6px 8px;
        }
        QListWidget#mediaDeckList {
            background: rgba(31, 38, 75, 122);
            border: 1px solid rgba(154, 167, 232, 58);
            padding: 8px;
        }
        QListWidget#mediaDeckList::item {
            min-height: 28px;
            padding: 5px 8px;
            border-radius: 6px;
        }
        QListWidget#mediaDeckList::item:selected {
            background: rgba(79, 123, 255, 128);
            color: #FFFFFF;
        }
        QTextBrowser#mainChatHistory, QPlainTextEdit#kneeboardEditor {
            padding: 8px;
        }
        QTextBrowser#squadmateList {
            background: rgba(31, 38, 75, 120);
            border: 1px solid rgba(125, 139, 205, 46);
            padding: 8px;
        }
        QHeaderView::section {
            background: rgba(38, 46, 86, 226);
            color: #AAB3D8;
            border: none;
            padding: 6px 8px;
        }
        QLabel#dialogStatusOk {
            color: #AAB3D8;
        }
        QLabel#dialogStatusError {
            color: #AAB3D8;
        }
        """
