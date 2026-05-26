from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from client.services.font_loader import build_font


NOTICE_TEXT = (
    "MAYDAY는 함대 통신과 플릿 트리 운용을 돕기 위한 보조 프로그램입니다.\n"
    "프로그램 사용 중 문제가 있으면 관리자에게 전달해 주세요.\n"
    "폰트와 일부 리소스는 원 저작권자의 권리를 존중하여 사용합니다.\n"
    "기여자 - TourniCat."
)


class NoticeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MAYDAY 공지")
        self.resize(520, 240)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("공지")
        title.setFont(build_font(13, 700))
        body = QLabel(NOTICE_TEXT)
        body.setWordWrap(True)
        body.setFont(build_font(9))
        close = QPushButton("닫기", clicked=self.close)

        layout.addWidget(title)
        layout.addWidget(body, 1)
        layout.addWidget(close)

        self.setStyleSheet(
            """
            QDialog {
                background: #0d151c;
                color: #dbe5ec;
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
