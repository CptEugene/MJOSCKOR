from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from client.services.font_loader import build_font
from shared.models.fleet_tree import FleetNode, FleetTreeModel, RoleName, RoleSlot, SquadNode, WingNode
from shared.models.fleet_tree_codec import decode_fleet_tree, encode_fleet_tree
from shared.models.fleet_tree_ids import (
    ensure_unique_tree_ids,
    next_unique_fleet_id,
    next_unique_slot_id,
    next_unique_squad_id,
    next_unique_wing_id,
)


ROLE_LABELS = {
    RoleName.COMMANDER: "커맨더",
    RoleName.OFFICER: "오피서",
    RoleName.PILOT: "파일럿",
    RoleName.SOLDIER: "솔저",
}


@dataclass(slots=True)
class NodeRef:
    kind: str
    fleet_id: str = ""
    wing_id: str = ""
    squad_id: str = ""
    slot_id: str = ""


class AdminDialog(QDialog):
    saveRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MAYDAY 플릿 트리 에디터")
        self.resize(980, 660)
        self.setMinimumSize(760, 480)
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._model = FleetTreeModel()
        self._tree_items: dict[tuple[str, str, str, str, str], QTreeWidgetItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("플릿 트리 에디터")
        title.setFont(build_font(13, 700))
        root.addWidget(title)

        hint = QLabel("노드를 선택해 이름을 바꾸거나 구조를 추가/삭제합니다.")
        hint.setFont(build_font(9))
        hint.setObjectName("dialogHint")
        root.addWidget(hint)

        self.status_label = QLabel("")
        self.status_label.setFont(build_font(8, 600))
        root.addWidget(self.status_label)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["플릿 트리", "역할"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.itemSelectionChanged.connect(self._sync_selection)
        body.addWidget(self.tree, 1)

        side_widget = QWidget()
        side_widget.setObjectName("editorSidePanel")
        side = QVBoxLayout(side_widget)
        side.setContentsMargins(0, 0, 8, 0)
        side.setSpacing(10)

        side.addWidget(QLabel("선택한 이름"))
        self.name_edit = QLineEdit()
        side.addWidget(self.name_edit)

        apply_name = QPushButton("이름 적용")
        apply_name.clicked.connect(self._apply_name)
        side.addWidget(apply_name)

        add_fleet = QPushButton("플릿 추가")
        add_fleet.clicked.connect(self._add_fleet)
        side.addWidget(add_fleet)

        add_wing = QPushButton("윙 추가")
        add_wing.clicked.connect(self._add_wing)
        side.addWidget(add_wing)

        add_squad = QPushButton("스쿼드 추가")
        add_squad.clicked.connect(self._add_squad)
        side.addWidget(add_squad)

        add_slot = QPushButton("슬롯 추가")
        add_slot.clicked.connect(self._add_slot)
        side.addWidget(add_slot)

        cycle_role = QPushButton("역할 변경")
        cycle_role.clicked.connect(self._cycle_role)
        side.addWidget(cycle_role)

        delete = QPushButton("삭제")
        delete.clicked.connect(self._delete_selected)
        side.addWidget(delete)

        side.addStretch(1)
        side_scroll = QScrollArea()
        side_scroll.setObjectName("editorSideScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setWidget(side_widget)
        body.addWidget(side_scroll, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        save = QPushButton("저장")
        save.clicked.connect(self._emit_save)
        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(save)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.setStyleSheet(
            """
            QDialog {
                background: #0d151c;
                color: #dbe5ec;
            }
            QLabel#dialogHint {
                color: #7f95a8;
            }
            QScrollArea#editorSideScroll {
                background: transparent;
                border: none;
            }
            QWidget#editorSidePanel {
                background: transparent;
            }
            QTreeWidget, QLineEdit {
                background: #0b1319;
                color: #dbe5ec;
                border: 1px solid #1a2834;
                border-radius: 8px;
                padding: 6px 8px;
            }
            QPushButton {
                background: #13202a;
                color: #dce6ee;
                border: 1px solid #263748;
                border-radius: 8px;
                min-height: 30px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: #172733;
            }
            """
        )

    def set_embedded_mode(self, enabled: bool) -> None:
        if enabled:
            self.setWindowFlag(Qt.WindowType.Widget, True)
            self.setModal(False)
            self.setSizeGripEnabled(False)
            self.close_button.hide()
        else:
            self.close_button.show()

    def set_tree_text(self, tree_text: str) -> None:
        self._model = decode_fleet_tree(tree_text) if tree_text.strip() else FleetTreeModel()
        ensure_unique_tree_ids(self._model)
        self.status_label.setText("")
        self._rebuild_tree()

    def set_status(self, message: str, ok: bool) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {'#68d391' if ok else '#f06b6b'};")

    def _rebuild_tree(self, selected_ref: NodeRef | None = None) -> None:
        if selected_ref is None:
            selected_ref = self._selected_ref()
        vertical_scroll = self.tree.verticalScrollBar().value()
        horizontal_scroll = self.tree.horizontalScrollBar().value()
        self._tree_items.clear()
        self.tree.clear()
        for fleet in self._model.fleets:
            fleet_ref = NodeRef(kind="fleet", fleet_id=fleet.fleet_id)
            fleet_item = QTreeWidgetItem([fleet.name, ""])
            fleet_item.setData(0, Qt.ItemDataRole.UserRole, fleet_ref)
            self._tree_items[self._node_key(fleet_ref)] = fleet_item
            self.tree.addTopLevelItem(fleet_item)
            for wing in fleet.wings:
                wing_ref = NodeRef(kind="wing", fleet_id=fleet.fleet_id, wing_id=wing.wing_id)
                wing_item = QTreeWidgetItem([wing.name, ""])
                wing_item.setData(0, Qt.ItemDataRole.UserRole, wing_ref)
                self._tree_items[self._node_key(wing_ref)] = wing_item
                fleet_item.addChild(wing_item)
                for squad in wing.squads:
                    squad_ref = NodeRef(
                        kind="squad",
                        fleet_id=fleet.fleet_id,
                        wing_id=wing.wing_id,
                        squad_id=squad.squad_id,
                    )
                    squad_item = QTreeWidgetItem([squad.name, ""])
                    squad_item.setData(0, Qt.ItemDataRole.UserRole, squad_ref)
                    self._tree_items[self._node_key(squad_ref)] = squad_item
                    wing_item.addChild(squad_item)
                    for slot in squad.role_slots:
                        slot_ref = NodeRef(
                            kind="slot",
                            fleet_id=fleet.fleet_id,
                            wing_id=wing.wing_id,
                            squad_id=squad.squad_id,
                            slot_id=slot.slot_id,
                        )
                        slot_item = QTreeWidgetItem([self._slot_display_name(slot), self._role_label(slot.role)])
                        slot_item.setData(0, Qt.ItemDataRole.UserRole, slot_ref)
                        self._tree_items[self._node_key(slot_ref)] = slot_item
                        squad_item.addChild(slot_item)
        self.tree.expandAll()
        self._restore_selection(selected_ref)
        self.tree.verticalScrollBar().setValue(vertical_scroll)
        self.tree.horizontalScrollBar().setValue(horizontal_scroll)
        self._sync_selection()

    def _sync_selection(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            self.name_edit.clear()
            return
        ref = self._selected_ref()
        if ref is None:
            self.name_edit.setText(item.text(0))
            return
        if ref.kind == "slot":
            slot = self._find_slot(ref.fleet_id, ref.wing_id, ref.squad_id, ref.slot_id)
            if slot is None:
                self.name_edit.setText(item.text(0))
                return
            self.name_edit.setText(slot.custom_name.strip() or self._role_label(slot.role))
            return
        self.name_edit.setText(item.text(0))

    def _selected_ref(self) -> NodeRef | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _apply_name(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        new_name = self.name_edit.text().strip()
        if not new_name:
            self.set_status("이름은 비워둘 수 없습니다.", ok=False)
            return
        if ref.kind == "fleet":
            fleet = self._find_fleet(ref.fleet_id)
            if fleet:
                fleet.name = new_name
        elif ref.kind == "wing":
            wing = self._find_wing(ref.fleet_id, ref.wing_id)
            if wing:
                wing.name = new_name
        elif ref.kind == "squad":
            squad = self._find_squad(ref.fleet_id, ref.wing_id, ref.squad_id)
            if squad:
                squad.name = new_name
        elif ref.kind == "slot":
            slot = self._find_slot(ref.fleet_id, ref.wing_id, ref.squad_id, ref.slot_id)
            if slot:
                slot.custom_name = new_name
        self._rebuild_tree(selected_ref=ref)
        self.set_status("이름을 변경했습니다.", ok=True)

    def _add_fleet(self) -> None:
        fleet_id = next_unique_fleet_id(self._model)
        fleet_number = fleet_id.rsplit("_", 1)[-1]
        self._model.fleets.append(FleetNode(fleet_id=fleet_id, name=f"플릿{fleet_number}", wings=[]))
        self._rebuild_tree(selected_ref=NodeRef(kind="fleet", fleet_id=fleet_id))

    def _add_wing(self) -> None:
        ref = self._selected_ref()
        if ref is None or ref.kind != "fleet":
            self.set_status("먼저 플릿을 선택하세요.", ok=False)
            return
        fleet = self._find_fleet(ref.fleet_id)
        if fleet is None:
            return
        wing_id = next_unique_wing_id(self._model)
        wing_number = wing_id.rsplit("_", 1)[-1]
        fleet.wings.append(WingNode(wing_id=wing_id, name=f"윙{wing_number}", squads=[]))
        self._rebuild_tree(selected_ref=ref)

    def _add_squad(self) -> None:
        ref = self._selected_ref()
        if ref is None or ref.kind != "wing":
            self.set_status("먼저 윙을 선택하세요.", ok=False)
            return
        wing = self._find_wing(ref.fleet_id, ref.wing_id)
        if wing is None:
            return
        squad_id = next_unique_squad_id(self._model)
        squad_number = squad_id.rsplit("_", 1)[-1]
        wing.squads.append(SquadNode(squad_id=squad_id, name=f"스쿼드{squad_number}", role_slots=[]))
        self._rebuild_tree(selected_ref=ref)

    def _add_slot(self) -> None:
        ref = self._selected_ref()
        if ref is None or ref.kind != "squad":
            self.set_status("먼저 스쿼드를 선택하세요.", ok=False)
            return
        squad = self._find_squad(ref.fleet_id, ref.wing_id, ref.squad_id)
        if squad is None:
            return
        squad.role_slots.append(RoleSlot(slot_id=next_unique_slot_id(self._model, squad.squad_id), role=RoleName.SOLDIER))
        self._rebuild_tree(selected_ref=ref)

    def _cycle_role(self) -> None:
        ref = self._selected_ref()
        if ref is None or ref.kind != "slot":
            self.set_status("먼저 슬롯을 선택하세요.", ok=False)
            return
        slot = self._find_slot(ref.fleet_id, ref.wing_id, ref.squad_id, ref.slot_id)
        if slot is None:
            return
        order = [RoleName.COMMANDER, RoleName.OFFICER, RoleName.PILOT, RoleName.SOLDIER]
        current_index = order.index(slot.role)
        slot.role = order[(current_index + 1) % len(order)]
        self._rebuild_tree(selected_ref=ref)

    def _delete_selected(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        next_ref = self._parent_ref(ref)
        if ref.kind == "fleet":
            self._model.fleets = [fleet for fleet in self._model.fleets if fleet.fleet_id != ref.fleet_id]
        elif ref.kind == "wing":
            fleet = self._find_fleet(ref.fleet_id)
            if fleet:
                fleet.wings = [wing for wing in fleet.wings if wing.wing_id != ref.wing_id]
        elif ref.kind == "squad":
            wing = self._find_wing(ref.fleet_id, ref.wing_id)
            if wing:
                wing.squads = [squad for squad in wing.squads if squad.squad_id != ref.squad_id]
        elif ref.kind == "slot":
            squad = self._find_squad(ref.fleet_id, ref.wing_id, ref.squad_id)
            if squad:
                squad.role_slots = [slot for slot in squad.role_slots if slot.slot_id != ref.slot_id]
        self._rebuild_tree(selected_ref=next_ref)

    def _emit_save(self) -> None:
        ensure_unique_tree_ids(self._model)
        self.saveRequested.emit(encode_fleet_tree(self._model))

    def _find_fleet(self, fleet_id: str) -> FleetNode | None:
        return next((fleet for fleet in self._model.fleets if fleet.fleet_id == fleet_id), None)

    @staticmethod
    def _role_label(role: RoleName) -> str:
        return ROLE_LABELS.get(role, role.value)

    def _slot_display_name(self, slot: RoleSlot) -> str:
        label = slot.custom_name.strip()
        if slot.occupant_callsign and label:
            return f"{label} [{slot.occupant_callsign}]"
        if slot.occupant_callsign:
            return slot.occupant_callsign
        if label:
            return label
        return f"{self._role_label(slot.role)} 슬롯"

    def _find_wing(self, fleet_id: str, wing_id: str) -> WingNode | None:
        fleet = self._find_fleet(fleet_id)
        if fleet is None:
            return None
        return next((wing for wing in fleet.wings if wing.wing_id == wing_id), None)

    def _find_squad(self, fleet_id: str, wing_id: str, squad_id: str) -> SquadNode | None:
        wing = self._find_wing(fleet_id, wing_id)
        if wing is None:
            return None
        return next((squad for squad in wing.squads if squad.squad_id == squad_id), None)

    def _find_slot(self, fleet_id: str, wing_id: str, squad_id: str, slot_id: str) -> RoleSlot | None:
        squad = self._find_squad(fleet_id, wing_id, squad_id)
        if squad is None:
            return None
        return next((slot for slot in squad.role_slots if slot.slot_id == slot_id), None)

    def _restore_selection(self, selected_ref: NodeRef | None) -> None:
        if selected_ref is None:
            return
        item = self._tree_items.get(self._node_key(selected_ref))
        if item is None:
            return
        self.tree.setCurrentItem(item)

    def _parent_ref(self, ref: NodeRef) -> NodeRef | None:
        if ref.kind == "slot":
            return NodeRef(kind="squad", fleet_id=ref.fleet_id, wing_id=ref.wing_id, squad_id=ref.squad_id)
        if ref.kind == "squad":
            return NodeRef(kind="wing", fleet_id=ref.fleet_id, wing_id=ref.wing_id)
        if ref.kind == "wing":
            return NodeRef(kind="fleet", fleet_id=ref.fleet_id)
        return None

    def _node_key(self, ref: NodeRef) -> tuple[str, str, str, str, str]:
        return (ref.kind, ref.fleet_id, ref.wing_id, ref.squad_id, ref.slot_id)
