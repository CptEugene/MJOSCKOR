from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RoleName(StrEnum):
    COMMANDER = "Commander"
    OFFICER = "Officer"
    PILOT = "Pilot"
    SOLDIER = "Soldier"

    @classmethod
    def coerce(cls, raw_value: object, default: "RoleName" | None = None) -> "RoleName":
        if isinstance(raw_value, cls):
            return raw_value
        normalized = str(raw_value or "").strip().lower()
        alias_map = {
            "commander": cls.COMMANDER,
            "officer": cls.OFFICER,
            "pilot": cls.PILOT,
            "sergeant": cls.PILOT,
            "soldier": cls.SOLDIER,
        }
        if normalized in alias_map:
            return alias_map[normalized]
        return default or cls.SOLDIER


class NodeType(StrEnum):
    FLEET = "fleet"
    WING = "wing"
    SQUAD = "squad"
    ROLE_SLOT = "role_slot"


@dataclass(slots=True)
class ChannelPermission:
    tx: bool
    rx: bool


@dataclass(slots=True)
class RolePermissionSet:
    ch1: ChannelPermission
    ch2: ChannelPermission
    ch3: ChannelPermission
    ch4: ChannelPermission

    def channel(self, channel_key: str) -> ChannelPermission:
        return getattr(self, channel_key)


ROLE_PERMISSIONS: dict[RoleName, RolePermissionSet] = {
    RoleName.COMMANDER: RolePermissionSet(
        ch1=ChannelPermission(tx=True, rx=True),
        ch2=ChannelPermission(tx=True, rx=True),
        ch3=ChannelPermission(tx=True, rx=True),
        ch4=ChannelPermission(tx=True, rx=True),
    ),
    RoleName.OFFICER: RolePermissionSet(
        ch1=ChannelPermission(tx=True, rx=True),
        ch2=ChannelPermission(tx=True, rx=True),
        ch3=ChannelPermission(tx=True, rx=True),
        ch4=ChannelPermission(tx=False, rx=True),
    ),
    RoleName.PILOT: RolePermissionSet(
        ch1=ChannelPermission(tx=True, rx=True),
        ch2=ChannelPermission(tx=False, rx=False),
        ch3=ChannelPermission(tx=True, rx=True),
        ch4=ChannelPermission(tx=False, rx=True),
    ),
    RoleName.SOLDIER: RolePermissionSet(
        ch1=ChannelPermission(tx=True, rx=True),
        ch2=ChannelPermission(tx=False, rx=False),
        ch3=ChannelPermission(tx=False, rx=True),
        ch4=ChannelPermission(tx=False, rx=True),
    ),
}


@dataclass(slots=True)
class RoleSlot:
    slot_id: str
    role: RoleName
    custom_name: str = ""
    occupant_callsign: str | None = None
    occupant_session_id: int | None = None
    is_speaking: bool = False
    active_channel: str = ""

    @property
    def display_name(self) -> str:
        label = self.custom_name.strip()
        if self.occupant_callsign and label:
            return f"{label} [{self.occupant_callsign}]"
        if self.occupant_callsign:
            return self.occupant_callsign
        if label:
            return label
        return f"No {self.role.value}"

    @property
    def empty(self) -> bool:
        return self.occupant_callsign is None


@dataclass(slots=True)
class SquadNode:
    squad_id: str
    name: str
    role_slots: list[RoleSlot] = field(default_factory=list)


@dataclass(slots=True)
class WingNode:
    wing_id: str
    name: str
    squads: list[SquadNode] = field(default_factory=list)


@dataclass(slots=True)
class FleetNode:
    fleet_id: str
    name: str
    wings: list[WingNode] = field(default_factory=list)


@dataclass(slots=True)
class FleetTreeModel:
    fleets: list[FleetNode] = field(default_factory=list)


@dataclass(slots=True)
class SlotPresence:
    session_id: int
    callsign: str
    fleet_id: str
    wing_id: str
    squad_id: str
    slot_id: str
    role: RoleName
    channel_tag: str = ""
    is_speaking: bool = False
