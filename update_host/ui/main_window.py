from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from client.services.font_loader import build_font
from update_host.services.config import UpdateHostConfig, UpdateHostConfigStore, open_in_file_explorer
from update_host.services.http_host import CloudviewUpdateHttpHost


class UpdateHostWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config_store = UpdateHostConfigStore()
        self.config = self.config_store.load()
        self.host = CloudviewUpdateHttpHost()

        self.setWindowTitle("Cloudview Update Host")
        self.setMinimumSize(620, 410)
        self.resize(720, 460)
        self._build_ui()
        self._sync_state()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.host.stop()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title = QLabel("Cloudview Update Host")
        title.setObjectName("title")
        title.setFont(build_font(22, 900))
        layout.addWidget(title)

        subtitle = QLabel("MAYDAY update manifest and package files are served from one folder.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setFont(build_font(10, 700))
        layout.addWidget(subtitle)

        settings = QFrame()
        settings.setObjectName("card")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(10)

        folder_label = QLabel("Update Folder")
        folder_label.setObjectName("label")
        settings_layout.addWidget(folder_label)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(self.config.update_dir))
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._browse_folder)
        open_button = QPushButton("Open")
        open_button.clicked.connect(self._open_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        folder_row.addWidget(open_button)
        settings_layout.addLayout(folder_row)

        port_label = QLabel("Port")
        port_label.setObjectName("label")
        settings_layout.addWidget(port_label)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(self.config.port)
        settings_layout.addWidget(self.port_spin)
        layout.addWidget(settings)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("START")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("STOP")
        self.stop_button.clicked.connect(self._stop)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel("Stopped")
        self.status_label.setObjectName("status")
        self.status_label.setFont(build_font(10, 800))
        layout.addWidget(self.status_label)

        self.url_box = QTextEdit()
        self.url_box.setReadOnly(True)
        self.url_box.setPlaceholderText("Start the host to see update URLs.")
        layout.addWidget(self.url_box, 1)

        self.setCentralWidget(root)
        self.setStyleSheet(self._stylesheet())

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select update folder", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)
            self._save_config_from_ui()

    def _open_folder(self) -> None:
        self._save_config_from_ui()
        open_in_file_explorer(self.config.update_dir)

    def _start(self) -> None:
        self._save_config_from_ui()
        try:
            status = self.host.start(self.config.update_dir, self.config.port)
        except OSError as exc:
            QMessageBox.warning(self, "Start failed", f"Port {self.config.port} is unavailable.\n\n{exc}")
            return
        except Exception as exc:
            QMessageBox.warning(self, "Start failed", str(exc))
            return
        self.url_box.setPlainText("\n".join(status.urls))
        self.status_label.setText(f"Running: {status.directory} on port {status.port}")
        self._sync_state()

    def _stop(self) -> None:
        self.host.stop()
        self.status_label.setText("Stopped")
        self.url_box.clear()
        self._sync_state()

    def _save_config_from_ui(self) -> None:
        self.config = UpdateHostConfig(
            update_dir=Path(self.folder_edit.text().strip()).expanduser(),
            port=int(self.port_spin.value()),
        )
        self.config_store.save(self.config)

    def _sync_state(self) -> None:
        running = self.host.running
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.folder_edit.setEnabled(not running)
        self.port_spin.setEnabled(not running)

    def _stylesheet(self) -> str:
        return """
            QWidget#root {
                background: #071018;
                color: #edf7fb;
            }
            QLabel#title {
                color: #f4fbff;
            }
            QLabel#muted {
                color: #b8c9d0;
            }
            QLabel#label {
                color: #d8e7ec;
                font-weight: 800;
            }
            QLabel#status {
                color: #85e6ff;
            }
            QFrame#card {
                background: rgba(255, 255, 255, 0.065);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 16px;
            }
            QLineEdit, QSpinBox, QTextEdit {
                background: rgba(0, 0, 0, 0.28);
                border: 1px solid rgba(133, 230, 255, 0.25);
                border-radius: 10px;
                color: #edf7fb;
                padding: 8px 10px;
            }
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 12px;
                color: #edf7fb;
                padding: 9px 16px;
                font-weight: 800;
            }
            QPushButton#primaryButton {
                background: #1a8aa7;
                border-color: #55d7ff;
                color: #ffffff;
            }
            QPushButton:disabled {
                color: rgba(237, 247, 251, 0.38);
                background: rgba(255, 255, 255, 0.045);
            }
        """
