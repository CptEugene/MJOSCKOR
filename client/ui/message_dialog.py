from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from client.services.font_loader import build_font


class AppMessageDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(620, 220)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        title_label = QLabel(title)
        title_label.setFont(build_font(12, 700))
        root.addWidget(title_label)

        row = QHBoxLayout()
        row.setSpacing(14)

        dot_wrap = QWidget()
        dot_wrap.setFixedWidth(28)
        dot_layout = QVBoxLayout(dot_wrap)
        dot_layout.setContentsMargins(0, 8, 0, 0)
        dot = QLabel("i")
        dot.setObjectName("infoDot")
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setFixedSize(28, 28)
        dot_layout.addWidget(dot)
        dot_layout.addStretch(1)

        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setFont(build_font(10, 500))
        text_label.setMinimumHeight(72)

        row.addWidget(dot_wrap)
        row.addWidget(text_label, 1)
        root.addLayout(row, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        ok_button = QPushButton("확인")
        ok_button.clicked.connect(self.accept)
        actions.addWidget(ok_button)
        root.addLayout(actions)

        self.setStyleSheet(
            """
            QDialog {
                background: #0f1820;
                color: #dce6ee;
            }
            QLabel {
                color: #dce6ee;
            }
            QLabel#infoDot {
                background: #2397f3;
                color: white;
                border-radius: 14px;
                font-weight: 700;
            }
            QPushButton {
                background: #13202a;
                color: #dce6ee;
                border: 1px solid #263748;
                border-radius: 8px;
                min-width: 96px;
                min-height: 36px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #172733;
            }
            """
        )
