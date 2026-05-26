from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from client.services.font_loader import build_font


@dataclass(slots=True)
class ChannelCardState:
    name: str
    channel_number: int
    binding: str
    active: bool = False
    enabled: bool = True


class ChannelCardWidget(QFrame):
    channelStepRequested = Signal(str, int)

    def __init__(self, state: ChannelCardState, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self.setObjectName("channelCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.name_label = QLabel(state.name.upper())
        self.name_label.setFont(build_font(11, 700))
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(6)
        channel_row.addStretch(1)
        self.channel_label = QLabel("채널")
        self.channel_label.setFont(build_font(9))
        self.channel_label.setObjectName("channelCaption")
        self.channel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.channel_down_button = QPushButton("<")
        self.channel_down_button.setObjectName("channelStepButton")
        self.channel_down_button.clicked.connect(lambda: self.channelStepRequested.emit(self._state.name, -1))
        self.channel_number_label = QLabel(str(state.channel_number))
        self.channel_number_label.setObjectName("channelNumber")
        self.channel_number_label.setFont(build_font(10, 800))
        self.channel_number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.channel_up_button = QPushButton(">")
        self.channel_up_button.setObjectName("channelStepButton")
        self.channel_up_button.clicked.connect(lambda: self.channelStepRequested.emit(self._state.name, 1))
        channel_row.addWidget(self.channel_label)
        channel_row.addWidget(self.channel_down_button)
        channel_row.addWidget(self.channel_number_label)
        channel_row.addWidget(self.channel_up_button)
        channel_row.addStretch(1)

        self.binding_label = QLabel(f"지정 키    {state.binding}")
        self.binding_label.setFont(build_font(9))
        self.binding_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.name_label)
        layout.addLayout(channel_row)
        layout.addWidget(self.binding_label)
        layout.addStretch(1)

        self._apply_state()

    def set_state(self, state: ChannelCardState) -> None:
        self._state = state
        self.name_label.setText(state.name.upper())
        self.channel_number_label.setText(str(state.channel_number))
        self.binding_label.setText(f"지정 키    {state.binding}")
        self._apply_state()

    def _apply_state(self) -> None:
        if not self._state.enabled:
            self.setStyleSheet(
                """
                QFrame#channelCard {
                    background: rgba(31, 38, 75, 190);
                    border: 1px solid rgba(125, 139, 205, 46);
                    border-radius: 10px;
                }
                QLabel {
                    color: rgba(234, 247, 255, 92);
                }
                QPushButton#channelStepButton {
                    background: transparent;
                    border: none;
                    color: rgba(234, 247, 255, 92);
                    min-width: 18px;
                    max-width: 18px;
                    min-height: 18px;
                    max-height: 18px;
                    padding: 0;
                }
                QLabel#channelNumber {
                    min-width: 22px;
                    color: rgba(234, 247, 255, 120);
                }
                """
            )
        elif self._state.active:
            self.setStyleSheet(
                """
                QFrame#channelCard {
                    background: rgba(79, 123, 255, 154);
                    border: 1px solid rgba(154, 167, 232, 128);
                    border-radius: 10px;
                }
                QLabel {
                    color: #FFFFFF;
                }
                QPushButton#channelStepButton {
                    background: transparent;
                    border: none;
                    color: #FFFFFF;
                    min-width: 18px;
                    max-width: 18px;
                    min-height: 18px;
                    max-height: 18px;
                    padding: 0;
                }
                QPushButton#channelStepButton:hover {
                    color: #AAB3D8;
                }
                QLabel#channelNumber {
                    min-width: 22px;
                    color: #FFFFFF;
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                QFrame#channelCard {
                    background: rgba(31, 38, 75, 190);
                    border: 1px solid rgba(125, 139, 205, 66);
                    border-radius: 10px;
                }
                QLabel {
                    color: #FFFFFF;
                }
                QPushButton#channelStepButton {
                    background: transparent;
                    border: none;
                    color: #AAB3D8;
                    min-width: 18px;
                    max-width: 18px;
                    min-height: 18px;
                    max-height: 18px;
                    padding: 0;
                }
                QPushButton#channelStepButton:hover {
                    color: #FFFFFF;
                }
                QLabel#channelNumber {
                    min-width: 22px;
                    color: #FFFFFF;
                }
                """
            )
