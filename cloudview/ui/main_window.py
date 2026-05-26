from __future__ import annotations

import os
from pathlib import Path
import random
import sys
from typing import Callable
import webbrowser

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QGraphicsOpacityEffect,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.services.font_loader import build_font
from cloudview.services.update_manager import (
    CLOUDVIEW_VERSION,
    CloudviewConfig,
    UpdateManager,
    UpdateManifest,
    default_install_dir,
)
from shared.constants.paths import runtime_paths


class _TaskWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(bool, str, object)

    def __init__(self, task: Callable[[Callable[[str, int], None]], object]) -> None:
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            result = self._task(lambda message, percent: self.progress.emit(message, percent))
            self.finished.emit(True, "완료", result)
        except Exception as exc:
            self.finished.emit(False, str(exc), None)


class BackgroundCarousel(QWidget):
    def __init__(self, image_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("backgroundCarousel")
        self._images = sorted(
            path
            for path in image_dir.glob("*")
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        )
        random.shuffle(self._images)
        self._index = 0
        self._current = QLabel(self)
        self._next = QLabel(self)
        self._veil = QWidget(self)
        self._veil.setObjectName("backgroundVeil")
        self._text_veil = QWidget(self)
        self._text_veil.setObjectName("backgroundTextVeil")
        for label in (self._current, self._next):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._animations: list[QPropertyAnimation] = []
        self._timer = QTimer(self)
        self._timer.setInterval(10_000)
        self._timer.timeout.connect(self._slide_next)
        self._apply_current_pixmap()
        if len(self._images) > 1:
            self._timer.start()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._current.setGeometry(0, 0, self.width(), self.height())
        self._next.setGeometry(self.width(), 0, self.width(), self.height())
        self._veil.setGeometry(0, 0, self.width(), self.height())
        self._text_veil.setGeometry(0, 0, int(self.width() * 0.58), self.height())
        self._apply_current_pixmap()

    def _slide_next(self) -> None:
        if len(self._images) < 2 or self.width() <= 0:
            return
        next_index = (self._index + 1) % len(self._images)
        self._set_label_pixmap(self._next, self._images[next_index])
        self._current.move(0, 0)
        self._next.move(self.width(), 0)

        current_animation = QPropertyAnimation(self._current, b"pos", self)
        current_animation.setDuration(900)
        current_animation.setStartValue(QPoint(0, 0))
        current_animation.setEndValue(QPoint(-self.width(), 0))
        current_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        next_animation = QPropertyAnimation(self._next, b"pos", self)
        next_animation.setDuration(900)
        next_animation.setStartValue(QPoint(self.width(), 0))
        next_animation.setEndValue(QPoint(0, 0))
        next_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._animations = [current_animation, next_animation]
        next_animation.finished.connect(lambda: self._finish_slide(next_index))
        current_animation.start()
        next_animation.start()

    def _finish_slide(self, next_index: int) -> None:
        self._index = next_index
        self._apply_current_pixmap()
        self._current.move(0, 0)
        self._next.move(self.width(), 0)
        self._animations = []

    def _apply_current_pixmap(self) -> None:
        if not self._images:
            return
        self._set_label_pixmap(self._current, self._images[self._index])

    def _set_label_pixmap(self, label: QLabel, path: Path) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)


class LauncherCanvas(QWidget):
    def __init__(self, background_dir: Path, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._background = BackgroundCarousel(background_dir, self)
        self._content = content
        self._content.setParent(self)
        self._background.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._background.lower()
        self._content.raise_()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        rect = self.rect()
        self._background.setGeometry(rect)
        self._content.setGeometry(rect)
        self._background.lower()
        self._content.raise_()


class CloudviewCenterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = CloudviewConfig()
        self.manager = UpdateManager(self.config)
        self._manifest: UpdateManifest | None = None
        self._cloudview_manifest: UpdateManifest | None = None
        self._mjo_patch_manifest: UpdateManifest | None = None
        self._thread: QThread | None = None
        self._worker: _TaskWorker | None = None
        self._primary_action = "launch"
        self._patch_action = "install"
        self._page_fade: QPropertyAnimation | None = None
        self._page_fade_out: QPropertyAnimation | None = None
        self._page_slide: QPropertyAnimation | None = None
        self._page_slide_out: QPropertyAnimation | None = None
        self._page_fade_overlay: QLabel | None = None
        self._log_messages: list[str] = []
        self._pending_task_result: tuple[
            bool,
            str,
            object,
            Callable[[object], None],
            bool,
        ] | None = None

        self.setWindowTitle("Cloudview Center")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(896, 560)
        self.resize(896, 560)
        self._build_ui()
        self._refresh_install_state()
        if "--resume-mayday-install" in sys.argv:
            QTimer.singleShot(650, self._resume_mayday_install)
        if "--resume-mjo-patch" in sys.argv:
            QTimer.singleShot(650, self._resume_mjo_patch_install)
        QTimer.singleShot(250, self._auto_check_update)
        QTimer.singleShot(1250, self._auto_check_cloudview_update)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_icon_rail(), 0)

        main = QWidget()
        main.setObjectName("mainSurface")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(14)

        main_layout.addWidget(self._build_header())

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("pageStack")
        self.page_stack.addWidget(self._build_home_page())
        self.page_stack.addWidget(self._build_mayday_card())
        self.page_stack.addWidget(self._build_patch_card())
        main_layout.addWidget(self.page_stack, 1)

        self.progress = QProgressBar()
        self.progress.setObjectName("installProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        main_layout.addWidget(self.progress)

        shell.addWidget(main, 1)
        central = LauncherCanvas(self._background_dir(), root)
        self.setCentralWidget(central)
        self.setStyleSheet(self._stylesheet())
        self._show_home_page()

    def _background_dir(self) -> Path:
        return self._cloudview_asset_dir() / "backgrounds"

    def _cloudview_asset_dir(self) -> Path:
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "cloudview")
        candidates.append(runtime_paths().assets_dir / "cloudview")
        candidates.append(Path(__file__).resolve().parents[2] / "assets" / "cloudview")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _build_icon_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("iconRail")
        rail.setFixedWidth(62)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(9, 16, 9, 16)
        layout.setSpacing(12)

        logo = QPushButton("")
        logo.setObjectName("railLogo")
        logo.setFixedSize(42, 42)
        logo.setToolTip("Home")
        logo.clicked.connect(self._show_home_page)
        logo_path = self._cloudview_asset_dir() / "icons" / "home.svg"
        if logo_path.exists():
            logo.setIcon(QIcon(str(logo_path)))
            logo.setIconSize(QSize(24, 24))
        layout.addWidget(logo)

        self.mayday_nav_button = QPushButton("")
        self.mayday_nav_button.setToolTip("MAYDAY")
        self.mayday_nav_button.setObjectName("railIcon")
        self.mayday_nav_button.setFixedSize(42, 42)
        mayday_icon_path = self._cloudview_asset_dir() / "icons" / "mayday.png"
        if mayday_icon_path.exists():
            self.mayday_nav_button.setIcon(QIcon(str(mayday_icon_path)))
            self.mayday_nav_button.setIconSize(QSize(32, 32))
        self.mayday_nav_button.clicked.connect(self._show_mayday_page)
        layout.addWidget(self.mayday_nav_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.patch_nav_button = QPushButton("")
        self.patch_nav_button.setToolTip("Component Language Pack")
        self.patch_nav_button.setObjectName("railIcon")
        self.patch_nav_button.setFixedSize(42, 42)
        patch_icon_path = self._cloudview_asset_dir() / "icons" / "starcitizen_patch_rounded.png"
        if patch_icon_path.exists():
            self.patch_nav_button.setIcon(QIcon(str(patch_icon_path)))
            self.patch_nav_button.setIconSize(QSize(30, 30))
        self.patch_nav_button.clicked.connect(self._show_patch_page)
        layout.addWidget(self.patch_nav_button, 0, Qt.AlignmentFlag.AlignHCenter)

        for button in [self.mayday_nav_button, self.patch_nav_button]:
            button.setProperty("selected", False)

        layout.addStretch(1)

        for icon_name, tooltip, url in [
            ("discord.svg", "MJO 디스코드", "https://discord.gg/4CjZjaPxw4"),
            ("naver.svg", "네이버 카페", "https://cafe.naver.com/44throyalengineers"),
        ]:
            link = QPushButton("")
            link.setObjectName("railLinkIcon")
            link.setFixedSize(38, 38)
            link.setToolTip(tooltip)
            link.clicked.connect(lambda checked=False, target=url: webbrowser.open(target))
            icon_path = self._cloudview_asset_dir() / "icons" / icon_name
            if icon_path.exists():
                link.setIcon(QIcon(str(icon_path)))
                link.setIconSize(QSize(22, 22))
            layout.addWidget(link, 0, Qt.AlignmentFlag.AlignHCenter)
        return rail

    def _show_home_page(self) -> None:
        self._switch_page(0)
        self.mayday_nav_button.setProperty("selected", False)
        self.patch_nav_button.setProperty("selected", False)
        self._refresh_nav_style()

    def _show_mayday_page(self) -> None:
        self._switch_page(1)
        self.mayday_nav_button.setProperty("selected", True)
        self.patch_nav_button.setProperty("selected", False)
        self._refresh_nav_style()

    def _show_patch_page(self) -> None:
        self._switch_page(2)
        self.mayday_nav_button.setProperty("selected", False)
        self.patch_nav_button.setProperty("selected", True)
        self._refresh_nav_style()
        self._refresh_patch_state()

    def _switch_page(self, index: int) -> None:
        old_index = self.page_stack.currentIndex()
        if old_index == index:
            return
        direction = 1 if index > old_index else -1
        travel = 28
        old_pixmap = self.page_stack.grab()
        overlay_parent = self.page_stack.parentWidget()
        overlay = QLabel(overlay_parent)
        overlay.setPixmap(old_pixmap)
        overlay.setGeometry(self.page_stack.geometry())
        overlay.show()
        overlay.raise_()
        self.page_stack.setCurrentIndex(index)

        new_widget = self.page_stack.currentWidget()
        new_widget.move(direction * travel, 0)
        new_effect = QGraphicsOpacityEffect(new_widget)
        new_effect.setOpacity(0.0)
        new_widget.setGraphicsEffect(new_effect)
        animation = QPropertyAnimation(new_effect, b"opacity", self)
        animation.setDuration(260)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutQuart)

        slide = QPropertyAnimation(new_widget, b"pos", self)
        slide.setDuration(260)
        slide.setStartValue(QPoint(direction * travel, 0))
        slide.setEndValue(QPoint(0, 0))
        slide.setEasingCurve(QEasingCurve.Type.OutQuart)

        def finish_new_page() -> None:
            new_widget.setGraphicsEffect(None)
            new_widget.move(0, 0)

        animation.finished.connect(finish_new_page)

        old_effect = QGraphicsOpacityEffect(overlay)
        old_effect.setOpacity(1.0)
        overlay.setGraphicsEffect(old_effect)
        fade_out = QPropertyAnimation(old_effect, b"opacity", self)
        fade_out.setDuration(260)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutQuart)

        start_pos = self.page_stack.geometry().topLeft()
        slide_out = QPropertyAnimation(overlay, b"pos", self)
        slide_out.setDuration(260)
        slide_out.setStartValue(start_pos)
        slide_out.setEndValue(start_pos - QPoint(direction * 14, 0))
        slide_out.setEasingCurve(QEasingCurve.Type.OutQuart)

        fade_out.finished.connect(overlay.deleteLater)

        self._page_fade_overlay = overlay
        self._page_fade = animation
        self._page_fade_out = fade_out
        self._page_slide = slide
        self._page_slide_out = slide_out
        animation.start()
        slide.start()
        fade_out.start()
        slide_out.start()

    def _refresh_nav_style(self) -> None:
        for button in [self.mayday_nav_button, self.patch_nav_button]:
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("launcherTopbar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)

        brand = QLabel("Cloudview Center")
        brand.setObjectName("topbarBrand")
        brand.setFont(build_font(13, 900))
        layout.addWidget(brand)

        layout.addStretch(1)

        version_label = QLabel(f"v{CLOUDVIEW_VERSION}")
        version_label.setObjectName("topbarVersion")
        version_label.setFont(build_font(9, 800))
        layout.addWidget(version_label)

        close_button = QPushButton("X")
        close_button.setObjectName("windowCloseButton")
        close_button.setFixedSize(30, 30)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
        return header

    def _build_mayday_card(self) -> QFrame:
        card = self._card()
        card.setObjectName("launcherPage")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        hero = QWidget()
        hero.setObjectName("launcherHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 24, 22, 24)
        hero_layout.setSpacing(19)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(12)

        self.mayday_state_pill = QLabel("INSTALL CHECK")
        self.mayday_state_pill.setObjectName("accentPill")
        self.mayday_state_pill.setFixedWidth(140)
        self.mayday_state_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mayday_state_pill.setFont(build_font(8, 900))
        hero_text.addWidget(self.mayday_state_pill)

        heading = QLabel("MAYDAY")
        heading.setObjectName("productTitle")
        heading.setFont(build_font(38, 900))
        heading.setFixedHeight(92)
        heading.setMaximumWidth(360)
        hero_text.addWidget(heading)

        subheading = QLabel(
            "MJO 전술 무전 시스템. Fleet tree, channel comms, overlay, media sync를 "
            "Cloudview Center에서 설치하고 관리합니다."
        )
        subheading.setObjectName("muted")
        subheading.setWordWrap(True)
        subheading.setFont(build_font(10, 700))
        subheading.setMaximumWidth(270)
        subheading.setFixedHeight(58)
        hero_text.addWidget(subheading)

        self.notes_label = QLabel("")
        self.notes_label.setObjectName("heroNotes")
        self.notes_label.setWordWrap(True)
        self.notes_label.setMaximumWidth(270)
        self.notes_label.hide()
        hero_text.addWidget(self.notes_label)

        action_row = QHBoxLayout()
        self.primary_action_button = QPushButton("LAUNCH")
        self.primary_action_button.setObjectName("primaryButton")
        self.primary_action_button.setFixedWidth(230)
        self.primary_action_button.clicked.connect(self._run_primary_action)
        self.launch_button = self.primary_action_button
        self.update_button = self.primary_action_button
        self.check_button = self.primary_action_button
        action_row.addWidget(self.primary_action_button)
        action_row.addStretch(1)
        hero_text.addLayout(action_row)
        hero_layout.addLayout(hero_text, 5)
        layout.addWidget(hero)

        self.install_dir_edit = QLineEdit(str(self.config.install_dir))
        self.install_dir_edit.hide()

        self.manifest_url_edit = QLineEdit(self.config.manifest_url)
        self.manifest_url_edit.setPlaceholderText("manifest.json URL 또는 로컬 파일 경로")
        self.manifest_url_edit.hide()
        layout.addStretch(1)
        return card

    def _build_home_page(self) -> QFrame:
        card = self._card()
        card.setObjectName("launcherPage")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        hero = QWidget()
        hero.setObjectName("launcherHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 24, 22, 24)
        hero_layout.setSpacing(12)

        title = QLabel("MJO")
        title.setObjectName("productTitle")
        title.setFont(build_font(42, 900))
        hero_layout.addWidget(title)

        subtitle = QLabel("Multinational Joint Operation")
        subtitle.setObjectName("muted")
        subtitle.setFont(build_font(12, 800))
        hero_layout.addWidget(subtitle)

        body = QLabel(
            "Cloudview Center는 MJO 커뮤니티의 작전 허브입니다. MAYDAY, 한글패치, "
            "커뮤니티 링크와 향후 도구들을 이곳에서 관리합니다."
        )
        body.setObjectName("muted")
        body.setWordWrap(True)
        body.setMaximumWidth(270)
        body.setFont(build_font(10, 700))
        hero_layout.addWidget(body)
        hero_layout.addStretch(1)

        layout.addWidget(hero, 1)
        return card

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_position"):
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _build_patch_card(self) -> QFrame:
        card = self._card()
        card.setObjectName("launcherPage")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        hero = QWidget()
        hero.setObjectName("launcherHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 24, 22, 24)
        hero_layout.setSpacing(19)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(12)

        self.patch_state_pill = QLabel("INSTALL CHECK")
        self.patch_state_pill.setObjectName("accentPill")
        self.patch_state_pill.setFixedWidth(140)
        self.patch_state_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.patch_state_pill.setFont(build_font(8, 900))
        hero_text.addWidget(self.patch_state_pill)

        heading = QLabel("COMPONENT\nLANGUAGE PACK")
        heading.setObjectName("productTitle")
        heading.setWordWrap(True)
        heading.setFixedHeight(92)
        heading.setMaximumWidth(360)
        heading.setFont(build_font(25, 900))
        hero_text.addWidget(heading)

        subheading = QLabel(
            "Star Citizen 언어팩 컴포넌트를 Cloudview Center에서 설치하고, "
            "서버 매니페스트와 비교해 업데이트 상태를 관리합니다."
        )
        subheading.setObjectName("muted")
        subheading.setWordWrap(True)
        subheading.setFont(build_font(10, 700))
        subheading.setMaximumWidth(270)
        subheading.setFixedHeight(58)
        hero_text.addWidget(subheading)

        self.patch_notes_label = QLabel("")
        self.patch_notes_label.setObjectName("heroNotes")
        self.patch_notes_label.setWordWrap(True)
        self.patch_notes_label.setMaximumWidth(270)
        self.patch_notes_label.hide()
        hero_text.addWidget(self.patch_notes_label)

        action_row = QHBoxLayout()
        self.patch_action_button = QPushButton("INSTALL")
        self.patch_action_button.setObjectName("primaryButton")
        self.patch_action_button.setFixedWidth(230)
        self.patch_action_button.clicked.connect(self._run_patch_action)
        action_row.addWidget(self.patch_action_button)
        action_row.addStretch(1)
        hero_text.addLayout(action_row)

        hero_layout.addLayout(hero_text, 5)
        layout.addWidget(hero)

        self.patch_source_edit = QLineEdit(self.config.patch_source)
        self.patch_source_edit.hide()

        self.patch_target_edit = QLineEdit(self.config.patch_target)
        self.patch_target_edit.hide()
        layout.addStretch(1)
        return card

    def _build_log_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QLabel("Activity Feed")
        heading.setObjectName("sectionTitle")
        heading.setFont(build_font(15, 800))
        layout.addWidget(heading)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Cloudview Center log")
        layout.addWidget(self.log, 1)
        return card

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        return card

    def _browse_install_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "MAYDAY 설치 경로 선택", self.install_dir_edit.text())
        if path:
            self.install_dir_edit.setText(path)
            self._save_config_from_ui()
            self._refresh_install_state()

    def _browse_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "manifest.json 선택", "", "JSON Files (*.json);;All Files (*)")
        if path:
            self.manifest_url_edit.setText(path)
            self._save_config_from_ui()

    def _browse_patch_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "MJO 한글패치 파일 선택", "", "All Files (*)")
        if path:
            self.patch_source_edit.setText(path)
            self._save_config_from_ui()

    def _browse_patch_target(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "MJO 한글패치 대상 경로 선택", self.patch_target_edit.text())
        if path:
            self.patch_target_edit.setText(path)
            self._save_config_from_ui()

    def _auto_detect_patch_target_if_empty(self) -> None:
        if not hasattr(self, "patch_target_edit"):
            return
        if not self.patch_source_edit.text().strip():
            detected_source = self.manager.detect_mjo_patch_source()
            if detected_source is not None:
                self.patch_source_edit.setText(str(detected_source))
                self._save_config_from_ui()
        if not self.patch_target_edit.text().strip():
            self._detect_patch_target(show_not_found=False)

    def _detect_patch_target(self, show_not_found: bool = True) -> None:
        detected = self.manager.detect_star_citizen_patch_target()
        if detected is None:
            if show_not_found:
                QMessageBox.information(
                    self,
                    "스타시티즌 경로 탐지",
                    "스타시티즌 설치 경로를 자동으로 찾지 못했습니다.\n대상 선택으로 직접 지정해주세요.",
                )
            return
        self.patch_target_edit.setText(str(detected))
        self._save_config_from_ui()
        self._append_log(f"Star Citizen path detected: {detected}")

    def _check_update(self) -> None:
        self._save_config_from_ui()

        def task(progress: Callable[[str, int], None]) -> UpdateManifest:
            progress("manifest 확인 중...", 10)
            manifest = self.manager.fetch_manifest(self.config.manifest_url)
            progress("버전 비교 완료", 100)
            return manifest

        self._run_task(task, self._on_manifest_checked, show_progress=False)

    def _auto_check_update(self) -> None:
        if self._thread is not None:
            return
        if not self.config.manifest_url.strip():
            return
        if not (self.config.install_dir / "Mayday.exe").exists():
            return

        def task(progress: Callable[[str, int], None]) -> UpdateManifest:
            progress("manifest auto check...", 10)
            return self.manager.fetch_manifest(self.config.manifest_url)

        self._run_task(
            task,
            self._on_auto_manifest_checked,
            show_progress=False,
            show_errors=False,
        )

    def _auto_check_cloudview_update(self) -> None:
        if self._thread is not None:
            QTimer.singleShot(1500, self._auto_check_cloudview_update)
            return
        if not self.config.cloudview_manifest_url.strip():
            return

        def task(progress: Callable[[str, int], None]) -> UpdateManifest:
            progress("Cloudview update check...", 10)
            return self.manager.fetch_cloudview_manifest()

        self._run_task(
            task,
            self._on_cloudview_manifest_checked,
            show_progress=False,
            show_errors=False,
        )

    def _auto_check_mjo_patch_update(self) -> None:
        if self._thread is not None:
            QTimer.singleShot(1500, self._auto_check_mjo_patch_update)
            return
        if not self.config.mjo_patch_manifest_url.strip():
            return

        def task(progress: Callable[[str, int], None]) -> UpdateManifest:
            progress("MJO Korean Patch update check...", 10)
            return self.manager.fetch_mjo_patch_manifest()

        self._run_task(
            task,
            self._on_mjo_patch_manifest_checked,
            show_progress=False,
            show_errors=False,
        )

    def _run_primary_action(self) -> None:
        if self._primary_action in {"install", "update"}:
            self._install_or_update()
            return
        self._launch_mayday()

    def _run_patch_action(self) -> None:
        if self._patch_action in {"install", "update"}:
            self._install_patch_placeholder()
            return
        self._uninstall_patch_placeholder()

    def _install_or_update(self, *, confirm_install_path: bool = True) -> None:
        self._save_config_from_ui()
        if self._primary_action == "install":
            install_dir = (
                self._choose_install_dir_for_install()
                if confirm_install_path
                else self._normalize_mayday_install_dir(self.config.install_dir)
            )
            if install_dir is None:
                self._append_log("MAYDAY install cancelled before selecting an install location.")
                return
            self.config.install_dir = install_dir
            self.install_dir_edit.setText(str(install_dir))
            self.config.save()
        if self._request_admin_restart_if_needed():
            return

        def task(progress: Callable[[str, int], None]) -> str:
            manifest = self._manifest or self.manager.fetch_manifest(self.config.manifest_url)
            package = self.manager.download_package(manifest, progress)
            self.manager.install_package(package, manifest, progress)
            return manifest.latest_version

        self._run_task(task, self._on_update_installed, show_progress=True)

    def _request_admin_restart_if_needed(self) -> bool:
        if not self.manager.install_requires_elevation(self.config.install_dir):
            return False
        message = (
            "이 설치 경로는 관리자 권한이 필요합니다.\n\n"
            f"{self.config.install_dir}\n\n"
            "Cloudview Center를 관리자 권한으로 다시 실행합니다."
        )
        QMessageBox.information(self, "관리자 권한 필요", message)
        if self.manager.relaunch_as_admin(["--resume-mayday-install"]):
            QApplication.quit()
            return True
        QMessageBox.warning(self, "권한 상승 실패", "관리자 권한 요청이 취소되었거나 실패했습니다.")
        return True

    def _resume_mayday_install(self) -> None:
        if self._thread is not None:
            QTimer.singleShot(1000, self._resume_mayday_install)
            return
        installed = (self.config.install_dir / "Mayday.exe").exists()
        self._primary_action = "update" if installed else "install"
        self._show_mayday_page()
        self._install_or_update(confirm_install_path=False)

    def _choose_install_dir_for_install(self) -> Path | None:
        install_dir = self._normalize_mayday_install_dir(default_install_dir())
        while True:
            action = self._show_install_path_dialog(install_dir)
            if action == "confirm":
                return install_dir
            if action == "cancel":
                return None
            if action != "change":
                return None

            start_dir = install_dir.parent
            while not start_dir.exists() and start_dir.parent != start_dir:
                start_dir = start_dir.parent
            selected = QFileDialog.getExistingDirectory(
                self,
                "MAYDAY 설치 경로 선택",
                str(start_dir),
            )
            if selected:
                install_dir = self._normalize_mayday_install_dir(Path(selected))

    def _show_install_path_dialog(self, install_dir: Path) -> str:
        dialog = QDialog(self)
        dialog.setObjectName("installPathDialog")
        dialog.setWindowTitle("MAYDAY 설치 경로")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        dialog.setStyleSheet(
            """
            QDialog#installPathDialog {
                background: #ffffff;
                color: #111820;
            }
            QDialog#installPathDialog QLabel {
                color: #111820;
            }
            QDialog#installPathDialog QLabel#installPath {
                background: #f0f5f7;
                border: 1px solid #bfd4dc;
                border-radius: 12px;
                color: #0b1117;
                padding: 12px;
            }
            QDialog#installPathDialog QPushButton {
                background: #0b5263;
                border: 1px solid #0b5263;
                border-radius: 13px;
                color: #ffffff;
                font-weight: 800;
                padding: 9px 16px;
                min-width: 78px;
            }
            QDialog#installPathDialog QPushButton:hover {
                background: #117187;
            }
            QDialog#installPathDialog QPushButton#cancelButton {
                background: #e7eef1;
                border: 1px solid #c1d0d6;
                color: #111820;
            }
            """
        )

        result = {"action": "cancel"}

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        title = QLabel("MAYDAY 설치 경로")
        title.setFont(build_font(15, 900))
        layout.addWidget(title)

        body = QLabel("MAYDAY를 아래 경로에 설치합니다.")
        body.setFont(build_font(10, 700))
        body.setWordWrap(True)
        layout.addWidget(body)

        path_label = QLabel(str(install_dir))
        path_label.setObjectName("installPath")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setFont(build_font(10, 800))
        layout.addWidget(path_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm_button = QPushButton("확인")
        change_button = QPushButton("경로 변경")
        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("cancelButton")
        buttons.addWidget(confirm_button)
        buttons.addWidget(change_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        def finish(action: str) -> None:
            result["action"] = action
            dialog.accept()

        confirm_button.clicked.connect(lambda: finish("confirm"))
        change_button.clicked.connect(lambda: finish("change"))
        cancel_button.clicked.connect(lambda: finish("cancel"))
        dialog.exec()
        return result["action"]

    def _normalize_mayday_install_dir(self, path: Path) -> Path:
        if path.name.lower() == "mayday":
            return path
        return path / "MAYDAY"

    def _launch_mayday(self) -> None:
        self._save_config_from_ui()
        try:
            self.manager.launch_mayday()
            self._append_log("MAYDAY 실행 요청 완료")
        except Exception as exc:
            QMessageBox.warning(self, "MAYDAY 실행 실패", str(exc))

    def _install_patch_placeholder(self, confirm_patch_path: bool = True) -> None:
        self._save_config_from_ui()
        if confirm_patch_path:
            patch_target = self._choose_patch_target_for_install()
            if patch_target is None:
                self._append_log("Component Language Pack install cancelled before selecting a target path.")
                return
            self.config.patch_target = str(patch_target)
            self.patch_target_edit.setText(str(patch_target))
            self.config.save()
        if self._request_patch_admin_restart_if_needed():
            return

        def task(progress: Callable[[str, int], None]) -> str:
            if self._mjo_patch_manifest is None:
                self._mjo_patch_manifest = self.manager.fetch_mjo_patch_manifest()
            return self.manager.install_mjo_patch_placeholder(progress, self._mjo_patch_manifest)

        self._run_task(task, self._on_mjo_patch_installed, show_progress=True)

    def _uninstall_patch_placeholder(self) -> None:
        self._save_config_from_ui()
        if self._request_patch_admin_restart_if_needed():
            return

        def task(progress: Callable[[str, int], None]) -> str:
            progress("MJO 한글패치 삭제 중...", 20)
            message = self.manager.uninstall_mjo_patch_placeholder()
            progress("MJO 한글패치 삭제 완료", 100)
            return message

        self._run_task(task, self._on_mjo_patch_uninstalled, show_progress=True)

    def _request_patch_admin_restart_if_needed(self) -> bool:
        if not self.manager.patch_requires_elevation():
            return False
        QMessageBox.information(
            self,
            "관리자 권한 필요",
            "스타시티즌 설치 폴더에 한글패치를 적용하려면 관리자 권한이 필요합니다.\n"
            "Cloudview Center를 관리자 권한으로 다시 실행합니다.",
        )
        if self.manager.relaunch_as_admin(["--resume-mjo-patch"]):
            QApplication.quit()
            return True
        QMessageBox.warning(self, "권한 상승 실패", "관리자 권한 요청이 취소되었거나 실패했습니다.")
        return True

    def _resume_mjo_patch_install(self) -> None:
        if self._thread is not None:
            QTimer.singleShot(1000, self._resume_mjo_patch_install)
            return
        self._show_patch_page()
        self._install_patch_placeholder(confirm_patch_path=False)

    def _choose_patch_target_for_install(self) -> Path | None:
        patch_target = self._initial_patch_target_dir()
        while True:
            action = self._show_component_path_dialog(patch_target)
            if action == "confirm":
                return patch_target
            if action == "cancel":
                return None
            if action != "change":
                return None

            start_dir = patch_target
            while not start_dir.exists() and start_dir.parent != start_dir:
                start_dir = start_dir.parent
            selected = QFileDialog.getExistingDirectory(
                self,
                "Component Language Pack 대상 경로 선택",
                str(start_dir),
            )
            if selected:
                patch_target = Path(selected)

    def _initial_patch_target_dir(self) -> Path:
        if self.config.patch_target.strip():
            return self._normalize_component_pack_target(Path(self.config.patch_target).expanduser())
        detected = self.manager.detect_star_citizen_patch_target()
        if detected is not None:
            return self._normalize_component_pack_target(detected)
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        return Path(program_files) / "Roberts Space Industries" / "StarCitizen" / "LIVE"

    def _normalize_component_pack_target(self, path: Path) -> Path:
        if path.name.lower() == "starcitizen":
            return path / "LIVE"
        return path

    def _show_component_path_dialog(self, patch_target: Path) -> str:
        dialog = QDialog(self)
        dialog.setObjectName("installPathDialog")
        dialog.setWindowTitle("Component Language Pack 설치 경로")
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        dialog.setStyleSheet(
            """
            QDialog#installPathDialog {
                background: #ffffff;
                color: #111820;
            }
            QDialog#installPathDialog QLabel {
                color: #111820;
            }
            QDialog#installPathDialog QLabel#installPath {
                background: #f0f5f7;
                border: 1px solid #bfd4dc;
                border-radius: 12px;
                color: #0b1117;
                padding: 12px;
            }
            QDialog#installPathDialog QPushButton {
                background: #0b5263;
                border: 1px solid #0b5263;
                border-radius: 13px;
                color: #ffffff;
                font-weight: 800;
                padding: 9px 16px;
                min-width: 78px;
            }
            QDialog#installPathDialog QPushButton:hover {
                background: #117187;
            }
            QDialog#installPathDialog QPushButton#cancelButton {
                background: #e7eef1;
                border: 1px solid #c1d0d6;
                color: #111820;
            }
            """
        )

        result = {"action": "cancel"}

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Component Language Pack 설치 경로")
        title.setFont(build_font(15, 900))
        layout.addWidget(title)

        body = QLabel("아래 경로에 컴포넌트 언어팩을 설치합니다.")
        body.setFont(build_font(10, 700))
        body.setWordWrap(True)
        layout.addWidget(body)

        path_label = QLabel(str(patch_target))
        path_label.setObjectName("installPath")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setFont(build_font(10, 800))
        layout.addWidget(path_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        confirm_button = QPushButton("확인")
        change_button = QPushButton("경로 변경")
        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("cancelButton")
        buttons.addWidget(confirm_button)
        buttons.addWidget(change_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        def finish(action: str) -> None:
            result["action"] = action
            dialog.accept()

        confirm_button.clicked.connect(lambda: finish("confirm"))
        change_button.clicked.connect(lambda: finish("change"))
        cancel_button.clicked.connect(lambda: finish("cancel"))
        dialog.exec()
        return result["action"]

    def _run_task(
        self,
        task: Callable[[Callable[[str, int], None]], object],
        on_success: Callable[[object], None],
        show_progress: bool = False,
        show_errors: bool = True,
    ) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "작업 진행 중", "이미 진행 중인 작업이 있습니다.")
            return
        self._set_busy(True)
        self.progress.setValue(0)
        self.progress.setVisible(show_progress)
        self._thread = QThread(self)
        self._worker = _TaskWorker(task)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._handle_progress)
        self._worker.finished.connect(
            lambda ok, message, result: self._capture_task_finished(
                ok,
                message,
                result,
                on_success,
                show_errors,
            )
        )
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._handle_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _capture_task_finished(
        self,
        ok: bool,
        message: str,
        result: object,
        on_success: Callable[[object], None],
        show_errors: bool,
    ) -> None:
        self._pending_task_result = (ok, message, result, on_success, show_errors)

    def _handle_thread_finished(self) -> None:
        self._set_busy(False)
        self.progress.hide()
        self._thread = None
        self._worker = None
        if self._pending_task_result is None:
            return
        ok, message, result, on_success, show_errors = self._pending_task_result
        self._pending_task_result = None
        if ok:
            on_success(result)
        else:
            self._append_log(f"실패: {message}")
            if show_errors:
                QMessageBox.warning(self, "작업 실패", message)

    def _handle_progress(self, message: str, percent: int) -> None:
        self.progress.setValue(max(0, min(100, percent)))
        self._append_log(message)

    def _on_manifest_checked(self, result: object) -> None:
        if not isinstance(result, UpdateManifest):
            return
        self._manifest = result
        installed = self.manager.read_installed_version()
        if self.manager.needs_update(installed, result):
            self._append_log("업데이트가 필요합니다.")
        else:
            self._append_log("현재 설치된 MAYDAY가 최신 요구 버전을 만족합니다.")
        self._refresh_install_state()

    def _on_auto_manifest_checked(self, result: object) -> None:
        if not isinstance(result, UpdateManifest):
            return
        self._manifest = result
        installed = self.manager.read_installed_version()
        if self.manager.needs_update(installed, result):
            self._append_log("MAYDAY update required after startup check")
            self._show_mayday_page()
        else:
            self._append_log("MAYDAY is up to date after startup check")
        self._refresh_install_state()

    def _on_mjo_patch_manifest_checked(self, result: object) -> None:
        if not isinstance(result, UpdateManifest):
            return
        self._mjo_patch_manifest = result
        installed = self.manager.read_installed_mjo_patch_version()
        if self.manager.needs_mjo_patch_update(installed, result):
            self._append_log("Component Language Pack update required after startup check")
        else:
            self._append_log("Component Language Pack is up to date after startup check")
        self._refresh_patch_state()

    def _on_cloudview_manifest_checked(self, result: object) -> None:
        if not isinstance(result, UpdateManifest):
            return
        self._cloudview_manifest = result
        if not self.manager.needs_cloudview_update(result):
            self._append_log("Cloudview Center is up to date after startup check")
            return
        answer = QMessageBox.question(
            self,
            "Cloudview 업데이트",
            (
                "Cloudview Center 새 버전이 있습니다.\n\n"
                f"현재 버전: {CLOUDVIEW_VERSION}\n"
                f"최신 버전: {result.latest_version}\n\n"
                "지금 업데이트를 진행할까요?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._install_cloudview_update(result)

    def _install_cloudview_update(self, manifest: UpdateManifest) -> None:
        if self._thread is not None:
            return

        def task(progress: Callable[[str, int], None]) -> Path:
            package = self.manager.download_cloudview_package(manifest, progress)
            self.manager.apply_cloudview_update(package, manifest)
            return package

        self._run_task(task, self._on_cloudview_update_ready, show_progress=True)

    def _on_cloudview_update_ready(self, result: object) -> None:
        self._append_log("Cloudview Center update prepared. Restarting for replacement.")
        QMessageBox.information(
            self,
            "Cloudview 업데이트",
            "Cloudview Center를 업데이트하기 위해 프로그램을 재시작합니다.",
        )
        QApplication.quit()

    def _on_update_installed(self, result: object) -> None:
        self._append_log(f"MAYDAY 설치 완료: {result}")
        self._refresh_install_state()
        QMessageBox.information(self, "완료 - Cloudview", "완료되었습니다.")

    def _on_mjo_patch_installed(self, result: object) -> None:
        self._append_log(str(result))
        self._refresh_patch_state()
        QMessageBox.information(self, "완료 - Cloudview", "완료되었습니다.")

    def _on_mjo_patch_uninstalled(self, result: object) -> None:
        self._append_log(str(result))
        self._refresh_patch_state()
        QMessageBox.information(self, "완료 - Cloudview", "완료되었습니다.")

    def _save_config_from_ui(self) -> None:
        self.config.install_dir = Path(self.install_dir_edit.text().strip())
        self.config.manifest_url = self.manifest_url_edit.text().strip()
        self.config.patch_source = self.patch_source_edit.text().strip()
        self.config.patch_target = self.patch_target_edit.text().strip()
        self.config.save()

    def _refresh_install_state(self) -> None:
        self.config.install_dir = Path(self.install_dir_edit.text().strip())
        version = self.manager.read_installed_version(self.config.install_dir)
        installed = (self.config.install_dir / "Mayday.exe").exists()
        self.mayday_state_pill.setText("READY" if installed else "NOT INSTALLED")

        if not installed:
            self._primary_action = "install"
            self.primary_action_button.setText("INSTALL")
            self.mayday_state_pill.setText("NOT INSTALLED")
        elif self._manifest and self.manager.needs_update(version, self._manifest):
            self._primary_action = "update"
            self.primary_action_button.setText("UPDATE")
            self.mayday_state_pill.setText("UPDATE REQUIRED")
        else:
            self._primary_action = "launch"
            self.primary_action_button.setText("LAUNCH")
            self.mayday_state_pill.setText("READY")

        self.primary_action_button.setEnabled(self._thread is None)
        if self._manifest and self._manifest.notes:
            self.notes_label.setText("\n".join(self._manifest.notes))
            self.notes_label.show()
        else:
            self.notes_label.clear()
            self.notes_label.hide()

    def _refresh_patch_state(self) -> None:
        if not hasattr(self, "patch_action_button"):
            return
        installed_version = self.manager.read_installed_mjo_patch_version()
        installed = installed_version is not None
        if not installed:
            self._patch_action = "install"
            self.patch_action_button.setText("INSTALL")
            self.patch_state_pill.setText("NOT INSTALLED")
        elif self._mjo_patch_manifest and self.manager.needs_mjo_patch_update(
            installed_version,
            self._mjo_patch_manifest,
        ):
            self._patch_action = "update"
            self.patch_action_button.setText("UPDATE")
            self.patch_state_pill.setText("UPDATE REQUIRED")
        else:
            self._patch_action = "uninstall"
            self.patch_action_button.setText("UNINSTALL")
            self.patch_state_pill.setText("READY")

        self.patch_action_button.setEnabled(self._thread is None)
        if self._mjo_patch_manifest and self._mjo_patch_manifest.notes:
            self.patch_notes_label.setText("\n".join(self._mjo_patch_manifest.notes))
            self.patch_notes_label.show()
        else:
            self.patch_notes_label.clear()
            self.patch_notes_label.hide()

    def _set_busy(self, busy: bool) -> None:
        self.primary_action_button.setEnabled(not busy)
        if hasattr(self, "patch_action_button"):
            self.patch_action_button.setEnabled(not busy)

    def _append_log(self, message: str) -> None:
        self._log_messages.append(message)
        if not hasattr(self, "log"):
            return
        self.log.appendPlainText(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _stylesheet(self) -> str:
        return """
            #root {
                background: transparent;
                color: #edf5f7;
            }
            #backgroundCarousel {
                background:
                    qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #05090d, stop: 0.42 #10171d, stop: 1 #24313a);
            }
            #backgroundVeil {
                background:
                    qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 rgba(42, 8, 58, 0.10),
                    stop: 0.48 rgba(8, 12, 20, 0.04),
                    stop: 1 rgba(4, 10, 16, 0.12));
            }
            #backgroundTextVeil {
                background:
                    qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(2, 4, 8, 0.76),
                    stop: 0.45 rgba(6, 8, 14, 0.48),
                    stop: 0.78 rgba(6, 8, 14, 0.16),
                    stop: 1 rgba(6, 8, 14, 0.00));
            }
            #mainSurface {
                background: transparent;
            }
            QMessageBox {
                background: #ffffff;
                color: #111820;
            }
            QMessageBox QLabel {
                color: #111820;
                background: transparent;
                font-weight: 700;
            }
            QMessageBox QPushButton {
                background: #0b5263;
                border: 1px solid #0b5263;
                border-radius: 12px;
                color: #ffffff;
                font-weight: 800;
                min-width: 78px;
                padding: 8px 14px;
            }
            QMessageBox QPushButton:hover {
                background: #117187;
            }
            QLabel {
                color: #edf5f7;
            }
            #iconRail {
                background: rgba(10, 9, 20, 0.34);
                border-right: 1px solid rgba(255, 255, 255, 0.08);
            }
            #railLogo {
                background: rgba(8, 14, 22, 0.42);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 15px;
                color: #f4fdff;
                min-height: 42px;
                max-height: 42px;
                padding: 0;
            }
            #railIcon, #railIconSelected {
                border-radius: 15px;
                padding: 0;
                color: #c7d4d9;
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.10);
            }
            #railIcon:hover {
                background: rgba(109, 219, 235, 0.18);
                border: 1px solid rgba(109, 219, 235, 0.36);
            }
            #railIconSelected, QPushButton[selected="true"] {
                background: rgba(113, 229, 245, 0.24);
                border: 1px solid rgba(174, 249, 255, 0.72);
                color: #ffffff;
            }
            #pageStack {
                background: transparent;
                border: none;
            }
            #railLinkIcon {
                border-radius: 14px;
                padding: 0;
                color: #e1fbff;
                background: rgba(36, 124, 145, 0.50);
                border: 1px solid rgba(112, 215, 235, 0.30);
            }
            #eyebrow, #statTitle {
                color: #6ec9d8;
                letter-spacing: 1.4px;
            }
            #topbar, #launcherTopbar, #card {
                background: transparent;
                border: none;
                border-radius: 22px;
            }
            #launcherTopbar {
                background: transparent;
                border: none;
                border-radius: 0;
            }
            #topbarBrand {
                color: #ffffff;
                letter-spacing: 1px;
            }
            #topbarVersion {
                color: #d7e3e8;
                background: rgba(8, 10, 16, 0.24);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 5px 10px;
            }
            #launcherPage {
                background: transparent;
                border: none;
            }
            #heroTitle {
                color: #f5fbff;
                letter-spacing: 1px;
            }
            #productTitle {
                color: #ffffff;
                letter-spacing: 3px;
            }
            #maydayHero, #launcherHero {
                background: transparent;
                border: none;
                border-radius: 0;
            }
            #launcherHero {
                min-height: 224px;
            }
            #muted {
                color: #d7e3e8;
            }
            #statePill, #accentPill {
                background: rgba(10, 15, 25, 0.32);
                border: 1px solid rgba(121, 234, 249, 0.38);
                color: #a6f7ff;
                border-radius: 18px;
                padding: 5px 12px;
            }
            #sectionTitle {
                color: #f5fbff;
            }
            #statCard {
                background: rgba(255, 255, 255, 0.045);
                border: 1px solid rgba(123, 197, 212, 0.16);
                border-radius: 16px;
            }
            #statValue {
                color: #ffffff;
            }
            #notesPanel {
                background: rgba(6, 13, 19, 0.62);
                border: 1px solid rgba(97, 172, 188, 0.22);
                border-radius: 16px;
                color: #c4d6dc;
                padding: 14px;
            }
            #heroNotes {
                background: rgba(8, 10, 16, 0.24);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 14px;
                color: #d8e6ea;
                padding: 10px;
            }
            #windowCloseButton {
                background: rgba(8, 10, 16, 0.28);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 17px;
                color: #dfe9ec;
                padding: 0;
            }
            #windowCloseButton:hover {
                background: rgba(210, 50, 70, 0.66);
                color: #ffffff;
            }
            QLineEdit, QPlainTextEdit {
                background: rgba(6, 13, 19, 0.82);
                color: #edf5f7;
                border: 1px solid rgba(89, 162, 178, 0.28);
                border-radius: 12px;
                padding: 10px;
                selection-background-color: #2f7c8f;
            }
            QPushButton {
                background: #214d5b;
                color: #f7fdff;
                border: 1px solid rgba(112, 215, 235, 0.34);
                border-radius: 13px;
                padding: 9px 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #2b6474;
            }
            #primaryButton {
                background: #d8f8ff;
                color: #061116;
                border: 1px solid #ffffff;
                padding: 10px 18px;
            }
            #primaryButton:hover {
                background: #ffffff;
            }
            #secondaryButton {
                background: #2c7688;
                border: 1px solid #70e0f2;
            }
            #ghostButton, #miniButton {
                background: rgba(255, 255, 255, 0.045);
                border: 1px solid rgba(112, 215, 235, 0.26);
            }
            QPushButton:disabled {
                background: #202b33;
                color: #788a93;
                border-color: #2f3c44;
            }
            QProgressBar {
                background: rgba(6, 13, 19, 0.82);
                color: #edf5f7;
                border: 1px solid rgba(89, 162, 178, 0.32);
                border-radius: 10px;
                text-align: center;
                min-height: 18px;
            }
            QProgressBar::chunk {
                background:
                    qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3ba3b9, stop: 1 #b8f8ff);
                border-radius: 10px;
            }
        """
