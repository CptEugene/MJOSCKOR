from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

from client.services.font_loader import build_font


class StartupSplash(QWidget):
    def __init__(self, icon_path: Path | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.SplashScreen
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("startupSplash")
        self._shown_at = time.monotonic()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        frame = QFrame(self)
        frame.setObjectName("startupSplashFrame")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(26, 26, 26, 22)
        frame_layout.setSpacing(14)

        self._icon_label = QLabel(frame)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedHeight(96)
        self._set_icon(icon_path)

        self._title_label = QLabel("MAYDAY", frame)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setFont(build_font(18, 800))

        self._status_label = QLabel("시스템 초기화 중...", frame)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setFont(build_font(9, 500))

        self._progress = QProgressBar(frame)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(12)

        frame_layout.addWidget(self._icon_label)
        frame_layout.addWidget(self._title_label)
        frame_layout.addWidget(self._status_label)
        frame_layout.addWidget(self._progress)
        root.addWidget(frame)

        self.setFixedSize(320, 250)
        self._center_on_screen()
        self.setStyleSheet(
            """
            QWidget#startupSplash {
                background: transparent;
            }
            QFrame#startupSplashFrame {
                background: rgba(9, 16, 23, 238);
                border: 1px solid rgba(39, 58, 74, 220);
                border-radius: 18px;
            }
            QLabel {
                color: #dce6ee;
            }
            QProgressBar {
                background: #0c141b;
                border: 1px solid #233543;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background: #5eb4ff;
                border-radius: 5px;
            }
            """
        )

    def set_progress(self, value: int, status_text: str) -> None:
        self._progress.setValue(max(0, min(100, int(value))))
        self._status_label.setText(status_text)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def close_with_minimum_duration(self, minimum_duration_ms: int = 650) -> None:
        app = QApplication.instance()
        minimum_duration_sec = max(0, int(minimum_duration_ms)) / 1000.0
        remaining = minimum_duration_sec - (time.monotonic() - self._shown_at)
        if app is not None:
            deadline = time.monotonic() + max(0.0, remaining)
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
        self.close()

    def _set_icon(self, icon_path: Path | None) -> None:
        if icon_path is None or not icon_path.exists():
            self._icon_label.setText("M")
            self._icon_label.setFont(build_font(34, 800))
            return
        pixmap = QPixmap(str(icon_path))
        if pixmap.isNull() and icon_path.suffix.lower() == ".ico":
            png_fallback = icon_path.with_suffix(".png")
            if png_fallback.exists():
                pixmap = QPixmap(str(png_fallback))
        if pixmap.isNull():
            self._icon_label.setText("M")
            self._icon_label.setFont(build_font(34, 800))
            return
        self._icon_label.setPixmap(
            pixmap.scaled(
                88,
                88,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _center_on_screen(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        screen = app.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            geometry.x() + (geometry.width() - self.width()) // 2,
            geometry.y() + (geometry.height() - self.height()) // 2,
        )
