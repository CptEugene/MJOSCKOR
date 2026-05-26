from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.services.font_loader import build_font
from shared.models.fleet_tree import FleetNode, FleetTreeModel, RoleName, RoleSlot, SquadNode, WingNode
from shared.models.fleet_tree_ids import compose_node_id


ROLE_LABELS = {
    RoleName.COMMANDER: "커맨더",
    RoleName.OFFICER: "오피서",
    RoleName.PILOT: "파일럿",
    RoleName.SOLDIER: "솔저",
}


@dataclass(slots=True)
class SlotActivation:
    fleet_id: str
    wing_id: str
    squad_id: str
    slot_id: str
    node_id: str
    role: str


class FleetTreeWidget(QWidget):
    slotActivated = Signal(object)
    createFleetRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fleetTree")
        self._model = FleetTreeModel()
        self._selected_fleet_id = ""
        self._selected_wing_id = ""
        self._selected_squad_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_fleet_list_page())
        self._stack.addWidget(self._build_situation_page())
        self._apply_style()

    def bind_model(self, model: FleetTreeModel) -> None:
        self._model = model
        if not self._selected_fleet_id and model.fleets:
            self._selected_fleet_id = model.fleets[0].fleet_id
        self._rebuild_fleet_cards()
        self._rebuild_situation()

    def refresh_presence(self, model: FleetTreeModel) -> None:
        self._model = model
        self._rebuild_situation()

    def _build_fleet_list_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("fleetListPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("플릿 목록")
        title.setObjectName("sectionPill")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(build_font(10, 800))
        create = QPushButton("플릿 생성")
        create.setObjectName("createButton")
        create.clicked.connect(self.createFleetRequested.emit)
        count = QLabel("설정된 플릿")
        count.setObjectName("muted")
        count.setFont(build_font(10, 700))
        top.addWidget(title)
        top.addWidget(create)
        top.addStretch(1)
        top.addWidget(count)
        layout.addLayout(top)

        self._fleet_scroll = QScrollArea(page)
        self._fleet_scroll.setWidgetResizable(True)
        self._fleet_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fleet_card_host = QWidget()
        self._fleet_card_grid = QGridLayout(self._fleet_card_host)
        self._fleet_card_grid.setContentsMargins(0, 0, 0, 0)
        self._fleet_card_grid.setSpacing(16)
        self._fleet_scroll.setWidget(self._fleet_card_host)
        layout.addWidget(self._fleet_scroll, 1)
        return page

    def _build_situation_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("situationPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        back = QPushButton("플릿 목록")
        back.setObjectName("ghostButton")
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._situation_title = QLabel("플릿 상황판")
        self._situation_title.setObjectName("situationTitle")
        self._situation_title.setFont(build_font(13, 900))
        header.addWidget(back)
        header.addWidget(self._situation_title, 1)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._squad_list = QFrame(page)
        self._squad_list.setObjectName("mobiglasPanel")
        self._squad_layout = QVBoxLayout(self._squad_list)
        self._squad_layout.setContentsMargins(10, 10, 10, 10)
        self._squad_layout.setSpacing(8)

        self._slot_panel = QFrame(page)
        self._slot_panel.setObjectName("mobiglasPanel")
        self._slot_layout = QVBoxLayout(self._slot_panel)
        self._slot_layout.setContentsMargins(14, 14, 14, 14)
        self._slot_layout.setSpacing(8)

        self._message_panel = QFrame(page)
        self._message_panel.setObjectName("mobiglasPanel")
        message_layout = QVBoxLayout(self._message_panel)
        message_layout.setContentsMargins(14, 14, 14, 14)
        message_layout.setSpacing(10)
        message_title = QLabel("정보")
        message_title.setObjectName("muted")
        message_title.setFont(build_font(9, 800))
        self._squad_summary = QLabel("스쿼드를 선택하세요")
        self._squad_summary.setObjectName("summaryText")
        self._squad_summary.setWordWrap(True)
        self._squad_summary.setFont(build_font(10, 700))
        message_layout.addWidget(message_title)
        message_layout.addWidget(self._squad_summary)
        message_layout.addStretch(1)

        body.addWidget(self._squad_list, 2)
        body.addWidget(self._slot_panel, 3)
        body.addWidget(self._message_panel, 2)
        layout.addLayout(body, 1)
        return page

    def _rebuild_fleet_cards(self) -> None:
        self._clear_layout(self._fleet_card_grid)
        if not self._model.fleets:
            empty = QLabel("설정된 플릿이 없습니다")
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fleet_card_grid.addWidget(empty, 0, 0, 1, 3)
            return
        for index, fleet in enumerate(self._model.fleets):
            row = index // 3
            column = index % 3
            self._fleet_card_grid.addWidget(self._build_fleet_card(fleet), row, column)
        for column in range(3):
            self._fleet_card_grid.setColumnStretch(column, 1)
        self._fleet_card_grid.setRowStretch((len(self._model.fleets) + 2) // 3, 1)

    def _build_fleet_card(self, fleet: FleetNode) -> QFrame:
        card = QFrame()
        card.setObjectName("fleetCard")
        card.setMinimumSize(326, 218)
        card.setMaximumWidth(360)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(18)
        badge = QLabel(self._badge_text(fleet.name))
        badge.setObjectName("fleetBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFont(build_font(18, 900))
        top_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        info_wrap = QVBoxLayout()
        info_wrap.setSpacing(8)
        name = QLabel(fleet.name.upper())
        name.setObjectName("fleetName")
        name.setFont(build_font(12, 900))
        name.setWordWrap(True)
        meta = QLabel(f"윙: {len(fleet.wings)}    스쿼드: {self._squad_count(fleet)}    슬롯: {self._slot_count(fleet)}")
        meta.setObjectName("muted")
        meta.setFont(build_font(9, 700))
        meta.setWordWrap(True)
        info_wrap.addWidget(name)
        info_wrap.addWidget(meta)
        info_wrap.addStretch(1)
        top_row.addLayout(info_wrap, 1)

        open_button = QPushButton("플릿 열기")
        open_button.setObjectName("joinButton")
        open_button.clicked.connect(lambda checked=False, fleet_id=fleet.fleet_id: self._open_fleet(fleet_id))
        layout.addLayout(top_row, 1)
        layout.addWidget(open_button)
        return card

    def _open_fleet(self, fleet_id: str) -> None:
        self._selected_fleet_id = fleet_id
        fleet = self._selected_fleet()
        if fleet and fleet.wings:
            self._selected_wing_id = fleet.wings[0].wing_id
            if fleet.wings[0].squads:
                self._selected_squad_id = fleet.wings[0].squads[0].squad_id
        self._rebuild_situation()
        self._stack.setCurrentIndex(1)

    def _rebuild_situation(self) -> None:
        if not hasattr(self, "_squad_layout"):
            return
        self._clear_layout(self._squad_layout)
        self._clear_layout(self._slot_layout)
        fleet = self._selected_fleet()
        if fleet is None:
            return
        self._situation_title.setText(f"{fleet.name.upper()} / 상황판")
        for wing in fleet.wings:
            wing_label = QLabel(wing.name.upper())
            wing_label.setObjectName("wingLabel")
            wing_label.setFont(build_font(9, 900))
            self._squad_layout.addWidget(wing_label)
            for squad in wing.squads:
                button = QPushButton(squad.name.upper())
                button.setObjectName("squadButtonSelected" if squad.squad_id == self._selected_squad_id else "squadButton")
                button.clicked.connect(
                    lambda checked=False, wing_id=wing.wing_id, squad_id=squad.squad_id: self._select_squad(wing_id, squad_id)
                )
                self._squad_layout.addWidget(button)
        self._squad_layout.addStretch(1)
        wing, squad = self._selected_wing_and_squad(fleet)
        if wing is None or squad is None:
            self._squad_summary.setText("스쿼드를 선택하세요")
            return
        self._squad_summary.setText(
            f"{wing.name} / {squad.name}\n"
            f"배치 인원: {self._occupied_count(squad)} / {len(squad.role_slots)}\n"
            "슬롯을 클릭하면 참가하거나 이동합니다."
        )
        for index, slot in enumerate(squad.role_slots):
            del index
            self._slot_layout.addWidget(self._build_slot_button(fleet, wing, squad, slot))
        self._slot_layout.addStretch(1)

    def _select_squad(self, wing_id: str, squad_id: str) -> None:
        self._selected_wing_id = wing_id
        self._selected_squad_id = squad_id
        self._rebuild_situation()

    def _build_slot_button(self, fleet: FleetNode, wing: WingNode, squad: SquadNode, slot: RoleSlot) -> QPushButton:
        has_occupant = bool(slot.occupant_callsign)
        occupant = slot.occupant_callsign or slot.custom_name.strip() or "빈 슬롯"
        button = QPushButton("")
        button.setObjectName("slotButtonSpeaking" if slot.is_speaking else ("slotButtonEmpty" if slot.empty else "slotButtonOccupied"))
        button.setFont(build_font(9, 800))
        button.setMinimumHeight(52)
        row = QHBoxLayout(button)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(12)
        role_label = QLabel(self._role_label(slot.role), button)
        role_label.setObjectName("slotRoleLabel")
        role_label.setStyleSheet(f"color: {self._role_color(slot.role)};")
        role_label.setFont(build_font(9, 900))
        role_label.setFixedWidth(112)
        role_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        occupant_label = QLabel(occupant, button)
        occupant_label.setObjectName("slotOccupantLabel")
        occupant_label.setStyleSheet(f"color: {'#FFFFFF' if has_occupant else 'rgba(170, 179, 216, 150)'};")
        occupant_label.setFont(build_font(9, 800))
        occupant_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(role_label)
        row.addWidget(occupant_label, 1)
        payload = SlotActivation(
            fleet_id=fleet.fleet_id,
            wing_id=wing.wing_id,
            squad_id=squad.squad_id,
            slot_id=slot.slot_id,
            node_id=compose_node_id(fleet.fleet_id, wing.wing_id, squad.squad_id),
            role=slot.role.value,
        )
        button.clicked.connect(lambda checked=False, activation=payload: self.slotActivated.emit(activation))
        return button

    @staticmethod
    def _role_color(role: RoleName) -> str:
        return {
            RoleName.COMMANDER: "#f4c65f",
            RoleName.OFFICER: "#6fc7ff",
            RoleName.PILOT: "#71d98f",
            RoleName.SOLDIER: "#b6c2cd",
        }.get(role, "#b6c2cd")

    @staticmethod
    def _role_label(role: RoleName) -> str:
        return ROLE_LABELS.get(role, role.value).upper()

    def _selected_fleet(self) -> FleetNode | None:
        for fleet in self._model.fleets:
            if fleet.fleet_id == self._selected_fleet_id:
                return fleet
        return self._model.fleets[0] if self._model.fleets else None

    def _selected_wing_and_squad(self, fleet: FleetNode) -> tuple[WingNode | None, SquadNode | None]:
        fallback_wing = fleet.wings[0] if fleet.wings else None
        fallback_squad = fallback_wing.squads[0] if fallback_wing and fallback_wing.squads else None
        for wing in fleet.wings:
            for squad in wing.squads:
                if squad.squad_id == self._selected_squad_id:
                    return wing, squad
        if fallback_wing and fallback_squad:
            self._selected_wing_id = fallback_wing.wing_id
            self._selected_squad_id = fallback_squad.squad_id
        return fallback_wing, fallback_squad

    @staticmethod
    def _clear_layout(layout) -> None:  # noqa: ANN001
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _badge_text(name: str) -> str:
        parts = [part for part in name.replace("_", " ").split() if part]
        if not parts:
            return "F"
        return "".join(part[0] for part in parts[:2]).upper()

    @staticmethod
    def _squad_count(fleet: FleetNode) -> int:
        return sum(len(wing.squads) for wing in fleet.wings)

    @staticmethod
    def _slot_count(fleet: FleetNode) -> int:
        return sum(len(squad.role_slots) for wing in fleet.wings for squad in wing.squads)

    @staticmethod
    def _occupied_count(squad: SquadNode) -> int:
        return sum(0 if slot.empty else 1 for slot in squad.role_slots)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#fleetTree, QWidget#fleetListPage, QWidget#situationPage {
                background: transparent;
                color: #FFFFFF;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QLabel#sectionPill {
                color: #FFFFFF;
                background: rgba(79, 123, 255, 96);
                border: 1px solid rgba(154, 167, 232, 86);
                border-radius: 18px;
                min-height: 38px;
                padding: 0 24px;
            }
            QPushButton#createButton {
                color: #FFFFFF;
                background: rgba(79, 123, 255, 146);
                border: 1px solid rgba(154, 167, 232, 96);
                border-radius: 18px;
                min-height: 38px;
                padding: 0 24px;
            }
            QPushButton#createButton:hover {
                background: rgba(79, 123, 255, 214);
                border: 1px solid rgba(154, 167, 232, 148);
            }
            QLabel#muted {
                color: rgba(170, 179, 216, 210);
            }
            QFrame#fleetCard {
                background: rgba(31, 38, 75, 194);
                border: 1px solid rgba(125, 139, 205, 68);
                border-radius: 13px;
            }
            QFrame#fleetCard:hover {
                background: rgba(79, 123, 255, 76);
                border: 1px solid rgba(154, 167, 232, 138);
            }
            QLabel#fleetBadge {
                color: #AAB3D8;
                background: rgba(31, 38, 75, 166);
                border: 1px solid rgba(154, 167, 232, 108);
                border-radius: 34px;
                min-width: 74px;
                max-width: 74px;
                min-height: 74px;
                max-height: 74px;
            }
            QLabel#fleetName, QLabel#situationTitle {
                color: #FFFFFF;
            }
            QPushButton#joinButton, QPushButton#ghostButton {
                color: #FFFFFF;
                background: rgba(79, 123, 255, 116);
                border: 1px solid rgba(154, 167, 232, 100);
                border-radius: 15px;
                min-height: 34px;
                padding: 0 18px;
            }
            QPushButton#joinButton:hover, QPushButton#ghostButton:hover {
                background: rgba(79, 123, 255, 196);
            }
            QFrame#mobiglasPanel {
                background: rgba(48, 56, 100, 202);
                border: 1px solid rgba(125, 139, 205, 74);
                border-radius: 10px;
            }
            QLabel#wingLabel {
                color: #FFFFFF;
                background: rgba(79, 123, 255, 80);
                border-radius: 6px;
                padding: 8px 10px;
            }
            QPushButton#squadButton, QPushButton#squadButtonSelected {
                text-align: left;
                color: #FFFFFF;
                background: rgba(31, 38, 75, 186);
                border: 1px solid rgba(125, 139, 205, 48);
                border-radius: 5px;
                min-height: 34px;
                padding: 0 10px;
            }
            QPushButton#squadButtonSelected {
                color: #FFFFFF;
                background: rgba(79, 123, 255, 152);
                border-left: 3px solid #AAB3D8;
            }
            QPushButton#slotButtonEmpty, QPushButton#slotButtonOccupied, QPushButton#slotButtonSpeaking {
                text-align: left;
                color: #FFFFFF;
                background: rgba(31, 38, 75, 194);
                border: 1px solid rgba(125, 139, 205, 56);
                border-radius: 7px;
                padding: 0 14px;
            }
            QPushButton#slotButtonOccupied {
                background: rgba(79, 123, 255, 110);
                border: 1px solid rgba(154, 167, 232, 100);
            }
            QPushButton#slotButtonSpeaking {
                color: #FFFFFF;
                background: rgba(79, 123, 255, 214);
                border: 1px solid rgba(154, 167, 232, 154);
            }
            QLabel#summaryText {
                color: #FFFFFF;
                line-height: 145%;
            }
            """
        )
