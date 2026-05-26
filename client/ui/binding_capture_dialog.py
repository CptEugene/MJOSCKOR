from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from client.input.bindings import MODIFIER_TOKENS
from client.input.bindings import normalize_binding
from client.input.bindings import should_replace_pending_binding
from client.input.input_monitor import InputMonitor
from client.services.font_loader import build_font


class BindingCaptureDialog(QDialog):
    def __init__(self, input_monitor: InputMonitor, parent=None) -> None:
        super().__init__(parent)
        self._input_monitor = input_monitor
        self._captured_binding = ""
        self._restore_joystick_enabled = self._input_monitor.joystick_enabled
        self._input_monitor.set_joystick_enabled(True, delay_seconds=0.0)
        self._baseline_tokens = self._input_monitor.snapshot()
        self._last_tokens = set(self._baseline_tokens)
        self._settle_until = time.monotonic() + 0.45
        self.setWindowTitle("키 입력 감지")
        self.resize(420, 180)
        self.setModal(True)
        self.finished.connect(self._restore_joystick_scan)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("키보드, 마우스, 조이스틱 버튼을 눌러주세요")
        title.setFont(build_font(11, 700))
        self.preview = QLabel("입력 대기 중...")
        self.preview.setFont(build_font(10, 600))
        self.preview.setObjectName("bindingPreview")
        hint = QLabel("예: CTRL+1, MOUSE4, CTRL+MOUSE5, JOY1_BTN1, JOY1_HAT1_UP")
        hint.setFont(build_font(8, 500))
        hint.setObjectName("bindingHint")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        use_button = QPushButton("사용")
        use_button.clicked.connect(self.accept)
        buttons.addWidget(use_button)
        buttons.addWidget(QPushButton("취소", clicked=self.reject))

        root.addWidget(title)
        root.addWidget(self.preview)
        root.addWidget(hint)
        root.addStretch(1)
        root.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_binding)
        self._timer.start(40)

        self.setStyleSheet(
            """
            QDialog {
                background: #0d151c;
                color: #dbe5ec;
            }
            QLabel#bindingPreview {
                color: #68d391;
            }
            QLabel#bindingHint {
                color: #7f95a8;
            }
            QPushButton {
                background: #13202a;
                color: #dce6ee;
                border: 1px solid #263748;
                border-radius: 8px;
                min-height: 30px;
                padding: 0 14px;
            }
            """
        )

    @property
    def captured_binding(self) -> str:
        return self._captured_binding

    def _restore_joystick_scan(self) -> None:
        self._input_monitor.set_joystick_enabled(self._restore_joystick_enabled)

    def _poll_binding(self) -> None:
        snapshot = self._input_monitor.snapshot()
        if time.monotonic() < self._settle_until:
            self._baseline_tokens = set(snapshot)
            self._last_tokens = set(snapshot)
            return

        active_tokens = snapshot - self._baseline_tokens
        new_tokens = snapshot - self._last_tokens
        self._last_tokens = set(snapshot)

        current = self._binding_from_tokens(active_tokens, new_tokens)
        if not current:
            return
        current = normalize_binding(current)
        if should_replace_pending_binding(self._captured_binding, current):
            self._captured_binding = current
            self.preview.setText(current)

    def _binding_from_tokens(self, tokens: set[str], new_tokens: set[str] | None = None) -> str:
        new_tokens = new_tokens or set()
        modifiers = [token for token in ("CTRL", "ALT", "SHIFT") if token in tokens]
        primaries = [
            token
            for token in tokens
            if token not in MODIFIER_TOKENS and token and token != "+"
        ]
        if not primaries:
            return ""
        primary = self._choose_primary_token(primaries, new_tokens)
        return "+".join([*modifiers, primary])

    @staticmethod
    def _choose_primary_token(primaries: list[str], new_tokens: set[str]) -> str:
        def priority(token: str) -> tuple[int, int, str]:
            is_new = 0 if token in new_tokens else 1
            if "_BTN" in token:
                kind = 0
            elif "_HAT" in token:
                kind = 1
            elif token.startswith("MOUSE"):
                kind = 2
            elif token.startswith("JOY") and "_AXIS" in token:
                kind = 4
            else:
                kind = 3
            return (is_new, kind, token)

        return sorted(primaries, key=priority)[0]
