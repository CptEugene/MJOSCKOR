from __future__ import annotations

from shared.models.fleet_tree import FleetNode, FleetTreeModel, RoleName, RoleSlot, SquadNode, WingNode


def default_role_slots(prefix: str) -> list[RoleSlot]:
    return [
        RoleSlot(slot_id=f"{prefix}_commander", role=RoleName.COMMANDER),
        RoleSlot(slot_id=f"{prefix}_officer", role=RoleName.OFFICER),
        RoleSlot(slot_id=f"{prefix}_pilot", role=RoleName.PILOT),
        RoleSlot(slot_id=f"{prefix}_soldier", role=RoleName.SOLDIER),
    ]


def build_default_fleet_tree() -> FleetTreeModel:
    return FleetTreeModel(
        fleets=[
            FleetNode(
                fleet_id="fleet_1",
                name="Fleet1",
                wings=[
                    WingNode(
                        wing_id="wing_1",
                        name="Wing1",
                        squads=[
                            SquadNode(
                                squad_id="squad_1",
                                name="Squad1",
                                role_slots=default_role_slots("squad_1"),
                            ),
                            SquadNode(
                                squad_id="squad_2",
                                name="Squad2",
                                role_slots=default_role_slots("squad_2"),
                            ),
                        ],
                    )
                ],
            )
        ]
    )
