from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.services.font_loader import build_font
from client.models.audio import AudioDeviceInfo
from client.ui.binding_capture_dialog import BindingCaptureDialog
from client.input.bindings import normalize_binding
from shared.constants.channels import CHANNEL_DISPLAY_NAMES, CHANNEL_LIMITS, CHANNEL_TAG_ORDER
from shared.models.app_settings import AppSettings


class SettingsDialog(QDialog):
    _DEVICE_INDEX_ROLE = int(Qt.ItemDataRole.UserRole)
    _DEVICE_NAME_ROLE = _DEVICE_INDEX_ROLE + 1
    _DEVICE_ENDPOINT_ROLE = _DEVICE_INDEX_ROLE + 2

    def __init__(self, input_monitor, parent=None) -> None:
        super().__init__(parent)
        self._input_monitor = input_monitor
        self.setWindowTitle("\uC635\uC158")
        self.resize(920, 720)
        self.setModal(False)

        self._binding_edits: list[QLineEdit] = []
        self._channel_sliders: list[QSlider] = []
        self._channel_pan_combos: list[QComboBox] = []
        self._channel_assignments: list[int] = [0, 0, 0, 0]
        self.overlay_chat_size_combo = QComboBox()
        self.nickname_edit = QLineEdit()
        self.server_address_edit = QLineEdit()
        self.server_password_edit = QLineEdit()
        self.server_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.connect_button = QPushButton("접속")
        self.disconnect_button = QPushButton("접속 해제")

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(14, 14, 14, 14)
        self._root_layout.setSpacing(12)

        self._settings_shell = QFrame()
        self._settings_shell.setObjectName("settingsShell")
        shell_layout = QHBoxLayout(self._settings_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self._root_layout.addWidget(self._settings_shell, 1)

        self.section_list = QListWidget()
        self.section_list.setObjectName("settingsNav")
        self.section_list.setFixedWidth(170)
        self.section_list.addItem(QListWidgetItem("\uC0AC\uC6B4\uB4DC \uC124\uC815"))
        self.section_list.addItem(QListWidgetItem("\uAE30\uD0C0 \uC124\uC815"))
        self.section_list.setCurrentRow(0)
        shell_layout.addWidget(self.section_list)

        self._right_wrap = QVBoxLayout()
        self._right_wrap.setContentsMargins(16, 16, 16, 16)
        self._right_wrap.setSpacing(12)
        shell_layout.addLayout(self._right_wrap, 1)

        self._title_label = QLabel("\uC635\uC158")
        self._title_label.setFont(build_font(14, 700))
        self._right_wrap.addWidget(self._title_label)

        self.subtitle = QLabel("\uC7A5\uCE58, \uCC44\uB110 \uC0AC\uC6B4\uB4DC, PTT \uC124\uC815\uC744 \uAD00\uB9AC\uD569\uB2C8\uB2E4.")
        self.subtitle.setObjectName("settingsSubtitle")
        self.subtitle.setFont(build_font(9, 500))
        self._right_wrap.addWidget(self.subtitle)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._wrap_scroll_page(self._build_sound_page()))
        self.pages.addWidget(self._wrap_scroll_page(self._build_other_page()))
        self._right_wrap.addWidget(self.pages, 1)
        self.section_list.currentRowChanged.connect(self.pages.setCurrentIndex)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_button = QPushButton("저장")
        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.save_button)
        actions.addWidget(self.close_button)
        self._right_wrap.addLayout(actions)

        self.setStyleSheet(
            """
            QDialog {
                background: rgba(16, 21, 48, 230);
                color: #ffffff;
            }
            QFrame#settingsShell {
                background: rgba(48, 56, 100, 202);
                border: 1px solid rgba(154, 167, 232, 86);
                border-radius: 8px;
            }
            QListWidget#settingsNav {
                background: rgba(18, 24, 55, 232);
                border: none;
                border-right: 1px solid rgba(154, 167, 232, 44);
                color: #ffffff;
                padding-top: 8px;
            }
            QListWidget#settingsNav::item {
                padding: 12px 14px;
                margin: 4px 8px;
                border-radius: 8px;
            }
            QListWidget#settingsNav::item:selected {
                background: rgba(79, 123, 255, 105);
                border: 1px solid rgba(154, 167, 232, 92);
            }
            QLabel {
                color: #ffffff;
            }
            QLabel#settingsSubtitle {
                color: #AAB3D8;
            }
            QLineEdit, QComboBox {
                background: rgba(31, 38, 75, 150);
                color: #ffffff;
                border: 1px solid rgba(125, 139, 205, 52);
                border-radius: 8px;
                padding: 6px 8px;
                min-height: 28px;
            }
            QSlider::groove:horizontal {
                background: rgba(31, 38, 75, 180);
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #4F7BFF;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QProgressBar {
                background: rgba(31, 38, 75, 150);
                border: 1px solid rgba(125, 139, 205, 52);
                border-radius: 8px;
                min-height: 18px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #4F7BFF;
                border-radius: 7px;
            }
            QPushButton {
                background: rgba(38, 46, 86, 218);
                color: #ffffff;
                border: 1px solid rgba(125, 139, 205, 70);
                border-radius: 8px;
                padding: 0 14px;
                min-height: 30px;
            }
            QPushButton:hover {
                background: rgba(79, 123, 255, 116);
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QFrame[sectionCard="true"] {
                background: rgba(31, 38, 75, 128);
                border: 1px solid rgba(154, 167, 232, 44);
                border-radius: 8px;
            }
            QDialog[embedded="true"] {
                background: transparent;
            }
            QFrame#settingsShell[embedded="true"] {
                background: transparent;
                border: none;
                border-radius: 0;
            }
            QFrame[sectionCard="true"][embedded="true"] {
                background: rgba(31, 38, 75, 82);
                border: none;
                border-radius: 8px;
            }
            """
        )

    def _wrap_scroll_page(self, content: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_sound_page(self) -> QWidget:
        page = QWidget()
        page.setAutoFillBackground(False)
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        devices_card = self._section_card("\uC0AC\uC6B4\uB4DC \uC124\uC815")
        devices_layout = devices_card.layout()
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.mic_combo = QComboBox()
        self.output_combo = QComboBox()
        self._populate_device_combo(self.mic_combo, [])
        self._populate_device_combo(self.output_combo, [])

        self.mic_slider = QSlider(Qt.Orientation.Horizontal)
        self.mic_slider.setRange(0, 200)
        self.mic_slider.setValue(100)
        self.mic_value_label = QLabel("100%")
        self.mic_slider.valueChanged.connect(lambda value: self.mic_value_label.setText(f"{value}%"))

        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setValue(0)
        self.mic_level_value = QLabel("0%")
        self.mic_level_start_button = QPushButton("측정 시작")
        self.mic_level_stop_button = QPushButton("측정 종료")

        self.output_slider = QSlider(Qt.Orientation.Horizontal)
        self.output_slider.setRange(0, 200)
        self.output_slider.setValue(100)
        self.output_value_label = QLabel("100%")
        self.output_slider.valueChanged.connect(lambda value: self.output_value_label.setText(f"{value}%"))

        self._add_form_row(grid, 0, "\uB9C8\uC774\uD06C \uC120\uD0DD", self.mic_combo)
        self._add_form_row(grid, 1, "\uB9C8\uC774\uD06C \uC778\uD48B \uB808\uBCA8", self._slider_wrap(self.mic_slider, self.mic_value_label))
        self._add_form_row(grid, 2, "\uB9C8\uC774\uD06C \uC778\uD48B \uCE21\uC815", self._meter_wrap(self.mic_level_bar, self.mic_level_value))
        self._add_form_row(grid, 3, "\uCE21\uC815 \uC81C\uC5B4", self._meter_controls_wrap())
        self._add_form_row(grid, 4, "\uC0AC\uC6B4\uB4DC \uC120\uD0DD", self.output_combo)
        self._add_form_row(grid, 5, "\uC0AC\uC6B4\uB4DC \uB808\uBCA8", self._slider_wrap(self.output_slider, self.output_value_label))
        devices_layout.addLayout(grid)
        layout.addWidget(devices_card)

        channel_card = self._section_card("\uCC44\uB110 \uC0AC\uC6B4\uB4DC")
        channel_layout = channel_card.layout()
        for channel_tag in CHANNEL_TAG_ORDER:
            display_name = CHANNEL_DISPLAY_NAMES[channel_tag].upper()
            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)

            receive_slider = QSlider(Qt.Orientation.Horizontal)
            receive_slider.setRange(0, 200)
            receive_slider.setValue(100)
            receive_value = QLabel("100%")
            receive_slider.valueChanged.connect(lambda value, target=receive_value: target.setText(f"{value}%"))
            self._channel_sliders.append(receive_slider)

            pan_combo = QComboBox()
            pan_combo.addItem("\uC591\uCE21", "both")
            pan_combo.addItem("\uC88C\uCE21", "left")
            pan_combo.addItem("\uC6B0\uCE21", "right")
            pan_combo.setMaximumWidth(120)
            self._channel_pan_combos.append(pan_combo)

            self._add_form_row(grid, 0, f"{display_name} \uC0AC\uC6B4\uB4DC \uB808\uBCA8", self._slider_wrap(receive_slider, receive_value))
            self._add_form_row(grid, 1, "\uCD9C\uB825 \uBC29\uD5A5", pan_combo)
            channel_layout.addLayout(grid)
        layout.addWidget(channel_card)
        layout.addStretch(1)
        return page

    def _build_other_page(self) -> QWidget:
        page = QWidget()
        page.setAutoFillBackground(False)
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        binding_card = self._section_card("\uAC01 \uCC44\uB110 PTT \uC124\uC815")
        binding_layout = binding_card.layout()
        for index, name in enumerate(("스쿼드", "지휘부", "관제/함선", "일반")):
            row = QHBoxLayout()
            label = QLabel(name)
            label.setMinimumWidth(92)
            edit = QLineEdit()
            edit.setReadOnly(True)
            button = QPushButton("입력 감지")
            button.clicked.connect(lambda _=False, idx=index: self._capture_binding(idx))
            row.addWidget(label)
            row.addWidget(edit, 1)
            row.addWidget(button)
            binding_layout.addLayout(row)
            self._binding_edits.append(edit)
        kneeboard_row = QHBoxLayout()
        kneeboard_label = QLabel("작전 메모")
        kneeboard_label.setMinimumWidth(92)
        self.kneeboard_binding_edit = QLineEdit()
        self.kneeboard_binding_edit.setReadOnly(True)
        kneeboard_button = QPushButton("입력 감지")
        kneeboard_button.clicked.connect(self._capture_kneeboard_binding)
        kneeboard_row.addWidget(kneeboard_label)
        kneeboard_row.addWidget(self.kneeboard_binding_edit, 1)
        kneeboard_row.addWidget(kneeboard_button)
        binding_layout.addLayout(kneeboard_row)
        layout.addWidget(binding_card)

        overlay_card = self._section_card("오버레이 설정")
        overlay_layout = overlay_card.layout()
        overlay_grid = QGridLayout()
        overlay_grid.setHorizontalSpacing(12)
        overlay_grid.setVerticalSpacing(12)
        self.overlay_chat_size_combo.addItem("작게", "small")
        self.overlay_chat_size_combo.addItem("보통", "normal")
        self.overlay_chat_size_combo.addItem("크게", "large")
        self._add_form_row(overlay_grid, 0, "채팅창 크기", self.overlay_chat_size_combo)
        overlay_layout.addLayout(overlay_grid)
        layout.addWidget(overlay_card)
        layout.addStretch(1)
        return page

    def _section_card(self, title_text: str) -> QFrame:
        card = QFrame()
        card.setProperty("sectionCard", True)
        self._apply_embedded_property(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel(title_text)
        title.setFont(build_font(10, 700))
        layout.addWidget(title)
        return card

    def _slider_wrap(self, slider: QSlider, value_label: QLabel) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        return widget

    def _meter_wrap(self, bar: QProgressBar, value_label: QLabel) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(bar, 1)
        layout.addWidget(value_label)
        return widget

    def _meter_controls_wrap(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.mic_level_start_button)
        layout.addWidget(self.mic_level_stop_button)
        layout.addStretch(1)
        return widget

    def _add_form_row(self, grid: QGridLayout, row: int, label_text: str, field: QWidget) -> None:
        label = QLabel(label_text)
        label.setFont(build_font(9, 600))
        grid.addWidget(label, row, 0)
        grid.addWidget(field, row, 1)

    def set_microphone_level(self, level: float) -> None:
        percent = max(0, min(100, round(level * 100)))
        self.mic_level_bar.setValue(percent)
        self.mic_level_value.setText(f"{percent}%")

    def load_from_settings(self, settings: AppSettings) -> None:
        self.nickname_edit.setText(settings.nickname)
        self.server_address_edit.setText(settings.server_address)
        self.server_password_edit.setText(settings.server_password)

        self._restore_device_selection(
            self.mic_combo,
            device_index=settings.microphone_device_index,
            device_name=settings.microphone_device_name,
            device_endpoint_id=settings.microphone_device_endpoint_id,
        )
        self._restore_device_selection(
            self.output_combo,
            device_index=settings.speaker_device_index,
            device_name=settings.speaker_device_name,
            device_endpoint_id=settings.speaker_device_endpoint_id,
        )

        self.mic_slider.setValue(settings.microphone_volume)
        self.output_slider.setValue(settings.speaker_volume)
        self._channel_assignments = list(settings.channel_assignments)

        for index, slider in enumerate(self._channel_sliders):
            slider.setValue(settings.channel_receive_volumes[index] if index < len(settings.channel_receive_volumes) else 100)
        for index, combo in enumerate(self._channel_pan_combos):
            value = settings.channel_pan_modes[index] if index < len(settings.channel_pan_modes) else "both"
            combo_index = combo.findData(value)
            if combo_index >= 0:
                combo.setCurrentIndex(combo_index)
        for index, edit in enumerate(self._binding_edits):
            edit.setText(
                normalize_binding(settings.channel_bindings[index]) if index < len(settings.channel_bindings) else ""
            )
        self.kneeboard_binding_edit.setText(normalize_binding(settings.kneeboard_binding))
        size_index = self.overlay_chat_size_combo.findData(settings.overlay_chat_size)
        if size_index < 0:
            size_index = self.overlay_chat_size_combo.findData("normal")
        self.overlay_chat_size_combo.setCurrentIndex(max(0, size_index))

    def to_settings(self) -> AppSettings:
        microphone_device_index, microphone_device_name, microphone_device_endpoint_id = self._current_device_selection(
            self.mic_combo
        )
        speaker_device_index, speaker_device_name, speaker_device_endpoint_id = self._current_device_selection(
            self.output_combo
        )
        return AppSettings(
            nickname=self.nickname_edit.text().strip() or "user",
            server_address=self.server_address_edit.text().strip() or "127.0.0.1",
            server_password=self.server_password_edit.text(),
            microphone_device_index=microphone_device_index,
            microphone_device_name=microphone_device_name,
            microphone_device_endpoint_id=microphone_device_endpoint_id,
            speaker_device_index=speaker_device_index,
            speaker_device_name=speaker_device_name,
            speaker_device_endpoint_id=speaker_device_endpoint_id,
            microphone_volume=self.mic_slider.value(),
            speaker_volume=self.output_slider.value(),
            channel_assignments=list(self._channel_assignments),
            channel_receive_volumes=[slider.value() for slider in self._channel_sliders],
            channel_pan_modes=[str(combo.currentData()) for combo in self._channel_pan_combos],
            channel_bindings=[
                normalize_binding(edit.text().strip() or str(index + 1)) for index, edit in enumerate(self._binding_edits)
            ],
            kneeboard_binding=normalize_binding(self.kneeboard_binding_edit.text().strip() or "F10"),
            overlay_chat_size=str(self.overlay_chat_size_combo.currentData() or "normal"),
        )

    def set_audio_devices(self, input_devices: list[AudioDeviceInfo], output_devices: list[AudioDeviceInfo]) -> None:
        current_input = self._current_device_selection(self.mic_combo)
        current_output = self._current_device_selection(self.output_combo)
        self._populate_device_combo(self.mic_combo, input_devices)
        self._populate_device_combo(self.output_combo, output_devices)
        self._restore_device_selection(
            self.mic_combo,
            device_index=current_input[0],
            device_name=current_input[1],
            device_endpoint_id=current_input[2],
        )
        self._restore_device_selection(
            self.output_combo,
            device_index=current_output[0],
            device_name=current_output[1],
            device_endpoint_id=current_output[2],
        )

    def _capture_binding(self, index: int) -> None:
        dialog = BindingCaptureDialog(self._input_monitor, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.captured_binding:
            self._binding_edits[index].setText(normalize_binding(dialog.captured_binding))

    def _capture_kneeboard_binding(self) -> None:
        dialog = BindingCaptureDialog(self._input_monitor, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.captured_binding:
            self.kneeboard_binding_edit.setText(normalize_binding(dialog.captured_binding))

    def select_section(self, index: int) -> None:
        index = max(0, min(self.pages.count() - 1, index))
        self.section_list.setCurrentRow(index)
        self.pages.setCurrentIndex(index)

    def set_embedded_mode(self, enabled: bool) -> None:
        self.setProperty("embedded", enabled)
        self._settings_shell.setProperty("embedded", enabled)
        for card in self.findChildren(QFrame):
            if card.property("sectionCard"):
                self._apply_embedded_property(card)
        if enabled:
            self.setWindowFlag(Qt.WindowType.Widget, True)
            self.setModal(False)
            self._root_layout.setContentsMargins(0, 0, 0, 0)
            self._root_layout.setSpacing(0)
            self._right_wrap.setContentsMargins(0, 0, 0, 0)
            self._right_wrap.setSpacing(10)
            self.section_list.hide()
            self._title_label.hide()
            self.subtitle.hide()
            self.close_button.hide()
        else:
            self._root_layout.setContentsMargins(14, 14, 14, 14)
            self._root_layout.setSpacing(12)
            self._right_wrap.setContentsMargins(16, 16, 16, 16)
            self._right_wrap.setSpacing(12)
            self.section_list.show()
            self._title_label.show()
            self.subtitle.show()
            self.close_button.show()
        self._refresh_style(self)
        self._refresh_style(self._settings_shell)
        for card in self.findChildren(QFrame):
            if card.property("sectionCard"):
                self._refresh_style(card)

    def _apply_embedded_property(self, widget: QWidget) -> None:
        widget.setProperty("embedded", bool(self.property("embedded")))

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _populate_device_combo(self, combo: QComboBox, devices: list[AudioDeviceInfo]) -> None:
        combo.clear()
        self._add_device_item(combo, "기본 장치", None, "", "")
        for device in devices:
            self._add_device_item(combo, device.name, device.index, device.name, device.endpoint_id)

    def _add_device_item(
        self,
        combo: QComboBox,
        label: str,
        device_index: int | None,
        device_name: str,
        device_endpoint_id: str,
    ) -> None:
        combo.addItem(label, device_index)
        item_index = combo.count() - 1
        combo.setItemData(item_index, device_index, self._DEVICE_INDEX_ROLE)
        combo.setItemData(item_index, device_name, self._DEVICE_NAME_ROLE)
        combo.setItemData(item_index, device_endpoint_id, self._DEVICE_ENDPOINT_ROLE)

    def _current_device_selection(self, combo: QComboBox) -> tuple[int | None, str, str]:
        index = combo.currentIndex()
        if index < 0:
            return None, "", ""
        device_index = combo.itemData(index, self._DEVICE_INDEX_ROLE)
        device_name = str(combo.itemData(index, self._DEVICE_NAME_ROLE) or "")
        device_endpoint_id = str(combo.itemData(index, self._DEVICE_ENDPOINT_ROLE) or "")
        return device_index, device_name, device_endpoint_id

    def _restore_device_selection(
        self,
        combo: QComboBox,
        *,
        device_index: int | None,
        device_name: str,
        device_endpoint_id: str,
    ) -> None:
        if combo.count() <= 0:
            return
        if device_endpoint_id:
            for index in range(combo.count()):
                if str(combo.itemData(index, self._DEVICE_ENDPOINT_ROLE) or "") == device_endpoint_id:
                    combo.setCurrentIndex(index)
                    return
        normalized_name = self._normalize_device_name(device_name)
        if normalized_name:
            for index in range(combo.count()):
                candidate_name = str(combo.itemData(index, self._DEVICE_NAME_ROLE) or "")
                if self._normalize_device_name(candidate_name) == normalized_name:
                    combo.setCurrentIndex(index)
                    return
        found_index = combo.findData(device_index)
        combo.setCurrentIndex(found_index if found_index >= 0 else 0)

    def _normalize_device_name(self, raw_name: str) -> str:
        name = raw_name.strip()
        if "[" in name:
            name = name.split("[", 1)[0].strip()
        return " ".join(name.split()).lower()
