from __future__ import annotations

from dataclasses import dataclass
import html

from PySide6.QtCore import QPoint, QEvent, QPauseAnimation, QPropertyAnimation, QRectF, QSequentialAnimationGroup, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from client.services.font_loader import build_font
from shared.models.chat import ChatMessage
from shared.models.fleet_tree import RoleName


@dataclass(slots=True)
class OverlayTalker:
    channel: str
    callsign: str
    is_self: bool = False


class RadioOverlayWidget(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._talkers: list[OverlayTalker] = []
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(420, 116)
        self.hide()

    def set_talkers(self, talkers: list[OverlayTalker]) -> None:
        self._talkers = talkers[:4]
        if not self._talkers:
            self.hide()
            return
        self._position_left_middle()
        self.show()
        self.update()

    def _position_left_middle(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.left() + 28
        y = geometry.top() + max(80, (geometry.height() // 2) - (self.height() // 2))
        self.move(QPoint(x, y))

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(build_font(10, 700))

        row_y = 14
        for talker in self._talkers:
            dot_color = QColor(255, 190, 74) if talker.is_self else QColor(91, 231, 120)
            channel_label = f"TX {talker.channel.upper()}" if talker.is_self else talker.channel.upper()

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_color)
            painter.drawEllipse(16, row_y + 4, 12, 12)

            painter.setPen(QPen(dot_color))
            painter.drawText(40, row_y + 16, channel_label)

            painter.setPen(QPen(QColor(241, 245, 249)))
            painter.drawText(150, row_y + 16, talker.callsign)
            row_y += 32


class MissionTextOverlayWidget(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._base_font_size = 20
        self.setObjectName("missionOverlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setFont(build_font(self._base_font_size, 800))
        self._label.setStyleSheet("color: rgba(244, 248, 251, 245); background: transparent;")
        layout.addWidget(self._label)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 220))
        self._label.setGraphicsEffect(shadow)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._animation = QSequentialAnimationGroup(self)
        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._hold = QPauseAnimation(self)
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._animation.addAnimation(self._fade_in)
        self._animation.addAnimation(self._hold)
        self._animation.addAnimation(self._fade_out)
        self._animation.finished.connect(self.hide)
        self.hide()

    def show_message(
        self,
        text: str,
        *,
        duration_ms: int = 3600,
        fade_ms: int = 450,
        color: str = "white",
        font_scale: float = 1.0,
    ) -> None:
        normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if not normalized:
            self.hide_now()
            return
        self._animation.stop()
        self._label.setText(normalized)
        self._apply_style(color=color, font_scale=font_scale)
        fade_duration = max(150, min(2000, int(fade_ms)))
        visible_duration = max(600, min(12_000, int(duration_ms)))
        hold_duration = max(0, visible_duration - (fade_duration * 2))
        self._fade_in.setDuration(fade_duration)
        self._fade_out.setDuration(fade_duration)
        self._hold.setDuration(hold_duration)
        self._opacity_effect.setOpacity(0.0)
        self._apply_geometry()
        self.show()
        self.raise_()
        self._animation.start()

    def hide_now(self) -> None:
        self._animation.stop()
        self._opacity_effect.setOpacity(0.0)
        self.hide()

    def _apply_style(self, *, color: str, font_scale: float) -> None:
        normalized_color = color.strip().lower()
        rgba = "rgba(244, 248, 251, 245)"
        if normalized_color == "green":
            rgba = "rgba(91, 231, 120, 245)"
        size = max(16, min(64, round(self._base_font_size * max(0.8, float(font_scale)))))
        self._label.setFont(build_font(size, 800))
        self._label.setStyleSheet(f"color: {rgba}; background: transparent;")

    def _apply_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        width = min(960, max(420, geometry.width() - 180))
        self.setFixedWidth(width)
        self._label.setFixedWidth(width - 48)
        self.adjustSize()
        x = geometry.center().x() - (self.width() // 2)
        y = geometry.top() + max(80, (geometry.height() // 2) - (self.height() // 2))
        self.move(QPoint(x, y))


class VideoOverlayWidget(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self._corner_radius = 26.0
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._handle_media_status_changed)
        self._player.errorOccurred.connect(self._handle_error)
        self._prepared_video_path = ""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(460, 256)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._shell = QFrame(self)
        self._shell.setObjectName("videoOverlayShell")
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)

        self._video_widget = QVideoWidget(self._shell)
        self._player.setVideoOutput(self._video_widget)
        shell_layout.addWidget(self._video_widget)
        layout.addWidget(self._shell)

        self.setStyleSheet(
            """
            QFrame#videoOverlayShell {
                background: rgba(7, 13, 18, 230);
                border: 1px solid rgba(166, 182, 196, 72);
                border-radius: 26px;
            }
            """
        )
        self.hide()

    def play_file(self, video_path: str, *, volume_percent: int = 10) -> bool:
        if self._prepared_video_path == video_path.strip():
            return self.play_prepared()
        if not self.prepare_file(video_path, volume_percent=volume_percent):
            return False
        return self.play_prepared()

    def prepare_file(self, video_path: str, *, volume_percent: int = 10) -> bool:
        normalized_path = video_path.strip()
        if not normalized_path:
            self.stop()
            return False
        self.stop()
        self._audio_output.setVolume(max(0.0, min(1.0, int(volume_percent) / 100.0)))
        self._player.setSource(QUrl.fromLocalFile(normalized_path))
        self._apply_masks()
        self._position_bottom_center()
        self._prepared_video_path = normalized_path
        return True

    def play_prepared(self) -> bool:
        if not self._prepared_video_path:
            return False
        self.show()
        self.raise_()
        self._player.play()
        return True

    def stop(self) -> None:
        self._player.stop()
        self._prepared_video_path = ""
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._apply_masks()
        self._position_bottom_center()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.stop()
        super().closeEvent(event)

    def _apply_masks(self) -> None:
        top_level_path = QPainterPath()
        top_level_path.addRoundedRect(QRectF(self.rect()), self._corner_radius, self._corner_radius)
        self.setMask(QRegion(top_level_path.toFillPolygon().toPolygon()))

        video_path = QPainterPath()
        video_path.addRoundedRect(QRectF(self._video_widget.rect()), self._corner_radius, self._corner_radius)
        self._video_widget.setMask(QRegion(video_path.toFillPolygon().toPolygon()))

    def _position_bottom_center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.center().x() - (self.width() // 2)
        y = geometry.bottom() - self.height() - 42
        self.move(QPoint(x, y))

    def _handle_media_status_changed(self, status) -> None:  # noqa: ANN001
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()

    def _handle_error(self, *args) -> None:  # noqa: ANN002
        del args
        self.stop()


class KneeboardOverlayWidget(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(420, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        shell = QFrame(self)
        shell.setObjectName("kneeboardOverlayShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(16, 16, 16, 16)
        shell_layout.setSpacing(10)

        title = QLabel("KNEEBOARD", shell)
        title.setFont(build_font(10, 800))
        shell_layout.addWidget(title)

        self._text = QTextBrowser(shell)
        self._text.setFrameShape(QFrame.Shape.NoFrame)
        self._text.setOpenLinks(False)
        self._text.setOpenExternalLinks(False)
        self._text.setReadOnly(True)
        self._text.document().setDocumentMargin(0)
        self._text.setFont(build_font(9, 600))
        shell_layout.addWidget(self._text, 1)

        layout.addWidget(shell)
        self.setStyleSheet(
            """
            QFrame#kneeboardOverlayShell {
                background: rgba(9, 16, 23, 226);
                border: 1px solid rgba(38, 55, 72, 225);
                border-radius: 18px;
            }
            """
        )
        self.hide()

    def set_text(self, text: str) -> None:
        padded_lines = [f" {line}" for line in text.splitlines()]
        self._text.setPlainText("\n" + "\n".join(padded_lines))

    def sync_visibility(self, visible: bool) -> None:
        if not visible:
            self.hide()
            return
        self._position_right_middle()
        self.show()
        self.raise_()

    def _position_right_middle(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.right() - self.width() - 28
        y = geometry.top() + max(80, (geometry.height() // 2) - (self.height() // 2))
        self.move(QPoint(x, y))


class RadioChatOverlayWidget(QWidget):
    messageSubmitted = Signal(str)
    inputClosed = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self._messages: list[ChatMessage] = []
        self._discard_initial_slash = False
        self._chat_size = "normal"
        self.setObjectName("chatOverlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._shell = QFrame(self)
        self._shell.setObjectName("chatShell")
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(18, 14, 18, 16)
        shell_layout.setSpacing(10)

        self._tabs = QFrame(self._shell)
        self._tabs.setObjectName("chatTabs")
        tabs_layout = QHBoxLayout(self._tabs)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(12)

        compose = QLabel("E", self._tabs)
        self._compose_label = compose
        compose.setObjectName("chatIcon")
        compose.setAlignment(Qt.AlignmentFlag.AlignCenter)
        compose.setFont(build_font(12, 900))
        compose.setFixedHeight(42)
        general = QLabel("GENERAL", self._tabs)
        self._general_label = general
        general.setObjectName("chatActiveTab")
        general.setAlignment(Qt.AlignmentFlag.AlignCenter)
        general.setFont(build_font(18, 900))
        general.setFixedHeight(42)
        bubble = QLabel("C", self._tabs)
        self._bubble_label = bubble
        bubble.setObjectName("chatIcon")
        bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bubble.setFont(build_font(12, 900))
        bubble.setFixedHeight(42)
        tabs_layout.addWidget(compose)
        tabs_layout.addWidget(general)
        tabs_layout.addStretch(1)
        tabs_layout.addWidget(bubble)

        self._history = QTextBrowser(self)
        self._history.setObjectName("chatHistory")
        self._history.setFrameShape(QFrame.Shape.NoFrame)
        self._history.setReadOnly(True)
        self._history.setOpenLinks(False)
        self._history.setOpenExternalLinks(False)
        self._history.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._history.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history.document().setDocumentMargin(0)
        self._history.setFont(build_font(12, 700))

        self._input = QLineEdit(self)
        self._input.setObjectName("chatInput")
        self._input.setPlaceholderText("GENERAL:")
        self._input.setFont(build_font(12, 800))
        self._input.setFixedHeight(46)
        self._input.hide()
        self._input.returnPressed.connect(self._submit_input)
        self._input.installEventFilter(self)

        shell_layout.addWidget(self._tabs)
        shell_layout.addWidget(self._history)
        shell_layout.addWidget(self._input)
        layout.addWidget(self._shell)

        self.setStyleSheet(
            """
            QWidget#chatOverlay {
                background: transparent;
                border: none;
            }
            QFrame#chatShell {
                background: transparent;
                border: none;
            }
            QFrame#chatShell[inputActive="true"] {
                background: rgba(18, 31, 43, 222);
                border: 1px solid rgba(96, 125, 153, 92);
                border-radius: 10px;
            }
            QFrame#chatTabs {
                background: transparent;
                border: none;
            }
            QLabel#chatIcon {
                color: #FFFFFF;
                background: rgba(42, 58, 76, 166);
                border: 1px solid rgba(96, 125, 153, 70);
                border-radius: 7px;
                min-width: 50px;
                min-height: 42px;
            }
            QLabel#chatActiveTab {
                color: #FFFFFF;
                background: rgba(31, 128, 94, 185);
                border: 1px solid rgba(98, 199, 151, 110);
                border-radius: 7px;
                min-width: 148px;
                min-height: 42px;
                padding-bottom: 2px;
            }
            QTextBrowser#chatHistory {
                background: transparent;
                color: #FFFFFF;
                border: none;
            }
            QLineEdit#chatInput {
                background: rgba(22, 38, 52, 184);
                color: #FFFFFF;
                border: 1px solid rgba(96, 125, 153, 62);
                border-radius: 8px;
                padding: 0 14px;
                selection-background-color: #1f805e;
            }
            """
        )

        self._sync_panel_chrome()
        self.set_chat_size("normal")
        self._apply_geometry()
        self.hide()

    def set_chat_size(self, size: str) -> None:
        normalized = str(size or "normal").strip().lower()
        if normalized not in {"small", "normal", "large"}:
            normalized = "normal"
        self._chat_size = normalized
        profile = self._size_profile()
        self.setFixedWidth(profile["width"])
        self._history.setFont(build_font(profile["history_font"], 700))
        self._input.setFont(build_font(profile["input_font"], 800))
        self._input.setFixedHeight(profile["input_height"])
        self._compose_label.setFont(build_font(profile["icon_font"], 900))
        self._general_label.setFont(build_font(profile["tab_font"], 900))
        self._bubble_label.setFont(build_font(profile["icon_font"], 900))
        for widget in (self._compose_label, self._general_label, self._bubble_label):
            widget.setFixedHeight(profile["tab_height"])
        self._apply_geometry()

    def set_messages(self, messages: list[ChatMessage]) -> None:
        self._messages = list(messages[-24:])
        self._refresh_history()
        self._refresh_visibility()

    def has_active_input(self) -> bool:
        return self._input.isVisible()

    def show_input(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._discard_initial_slash = True
        self._input.clear()
        self._input.show()
        self._sync_panel_chrome()
        self._apply_geometry()
        self.show()
        self.raise_()
        self.activateWindow()
        self.focus_input()

    def hide_input(self) -> None:
        was_visible = self._input.isVisible()
        self._discard_initial_slash = False
        self._input.clear()
        self._input.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._sync_panel_chrome()
        self._apply_geometry()
        self._refresh_visibility()
        if was_visible:
            self.inputClosed.emit()

    def focus_input(self) -> None:
        self.raise_()
        self.activateWindow()
        self._input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if watched is self._input and event.type() == QEvent.Type.KeyPress:
            if self._discard_initial_slash:
                self._discard_initial_slash = False
                if event.key() == Qt.Key.Key_Slash or event.text() == "/":
                    return True
            if event.key() == Qt.Key.Key_Escape:
                self.hide_input()
                return True
        return super().eventFilter(watched, event)

    def _submit_input(self) -> None:
        text = self._input.text().strip()
        if not text:
            self.hide_input()
            return
        self.messageSubmitted.emit(text)
        self.hide_input()

    def _refresh_history(self) -> None:
        if not self._messages:
            self._history.clear()
            return
        lines: list[str] = []
        for message in self._messages[-8:]:
            callsign = html.escape(message.callsign or "Unknown")
            text = html.escape(message.text)
            lines.append(
                (
                    "<div style='margin: 0 0 6px 0;'>"
                    f"<span style='color: {self._role_color(message.role)}; font-weight: 800;'>"
                    f"[GENERAL] {callsign}</span>"
                    f"<span style='color: #FFFFFF; font-weight: 650;'>: {text}</span>"
                    "</div>"
                )
            )
        self._history.setHtml("".join(lines))
        self._history.verticalScrollBar().setValue(self._history.verticalScrollBar().maximum())

    def _refresh_visibility(self) -> None:
        self._apply_geometry()
        if not self._messages and not self._input.isVisible():
            self.hide()
            return
        self.show()
        self.update()

    def _apply_geometry(self) -> None:
        input_active = self._input.isVisible()
        profile = self._size_profile()
        history_height = profile["active_history"] if input_active else profile["idle_history"]
        chrome_height = profile["tab_height"] if input_active else 0
        input_height = profile["input_height"] if input_active else 0
        content_spacing = 20 if input_active else 0
        shell_vertical_margins = 30
        total_height = shell_vertical_margins + chrome_height + history_height + input_height + content_spacing
        self._history.setFixedHeight(history_height)
        self.setFixedHeight(total_height)
        self._position_left_bottom()

    def _position_left_bottom(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.left() + 46
        y = geometry.bottom() - self.height() - 46
        self.move(QPoint(x, y))

    def _sync_panel_chrome(self) -> None:
        input_active = self._input.isVisible()
        self._tabs.setVisible(input_active)
        self._shell.setProperty("inputActive", "true" if input_active else "false")
        self._shell.style().unpolish(self._shell)
        self._shell.style().polish(self._shell)

    def _role_color(self, role: str) -> str:
        role_map = {
            RoleName.COMMANDER.value: "#AAB3D8",
            RoleName.OFFICER.value: "#4F7BFF",
            RoleName.PILOT.value: "#AAB3D8",
            "Sergeant": "#AAB3D8",
            RoleName.SOLDIER.value: "#FFFFFF",
        }
        return role_map.get(role, "#FFFFFF")

    def _size_profile(self) -> dict[str, int]:
        profiles = {
            "small": {
                "width": 620,
                "idle_history": 140,
                "active_history": 198,
                "history_font": 10,
                "input_font": 10,
                "icon_font": 10,
                "tab_font": 15,
                "tab_height": 36,
                "input_height": 40,
            },
            "normal": {
                "width": 760,
                "idle_history": 176,
                "active_history": 246,
                "history_font": 12,
                "input_font": 12,
                "icon_font": 12,
                "tab_font": 18,
                "tab_height": 42,
                "input_height": 46,
            },
            "large": {
                "width": 900,
                "idle_history": 214,
                "active_history": 304,
                "history_font": 14,
                "input_font": 14,
                "icon_font": 14,
                "tab_font": 21,
                "tab_height": 50,
                "input_height": 54,
            },
        }
        return profiles.get(self._chat_size, profiles["normal"])
