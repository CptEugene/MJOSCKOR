from __future__ import annotations

import json

from shared.models.fleet_tree import (
    FleetNode,
    FleetTreeModel,
    RoleName,
    RoleSlot,
    SquadNode,
    WingNode,
)


def encode_fleet_tree(model: FleetTreeModel) -> str:
    payload = {
        "fleets": [
            {
                "fleet_id": fleet.fleet_id,
                "name": fleet.name,
                "wings": [
                    {
                        "wing_id": wing.wing_id,
                        "name": wing.name,
                        "squads": [
                            {
                                "squad_id": squad.squad_id,
                                "name": squad.name,
                                "role_slots": [
                                    {
                                        "slot_id": slot.slot_id,
                                        "role": slot.role.value,
                                        "custom_name": slot.custom_name,
                                        "occupant_callsign": slot.occupant_callsign,
                                        "occupant_session_id": slot.occupant_session_id,
                                        "is_speaking": slot.is_speaking,
                                        "active_channel": slot.active_channel,
                                    }
                                    for slot in squad.role_slots
                                ],
                            }
                            for squad in wing.squads
                        ],
                    }
                    for wing in fleet.wings
                ],
            }
            for fleet in model.fleets
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def decode_fleet_tree(text: str) -> FleetTreeModel:
    raw = json.loads(text)
    fleets: list[FleetNode] = []
    for fleet_data in raw.get("fleets", []):
        wings: list[WingNode] = []
        for wing_data in fleet_data.get("wings", []):
            squads: list[SquadNode] = []
            for squad_data in wing_data.get("squads", []):
                role_slots: list[RoleSlot] = []
                for slot_data in squad_data.get("role_slots", []):
                    role = RoleName.coerce(slot_data.get("role", "Soldier"))
                    slot_id = str(slot_data["slot_id"])
                    if role is RoleName.PILOT and slot_id.endswith("_sergeant"):
                        slot_id = slot_id[: -len("_sergeant")] + "_pilot"
                    role_slots.append(
                        RoleSlot(
                            slot_id=slot_id,
                            role=role,
                            custom_name=str(slot_data.get("custom_name", "")).strip(),
                            occupant_callsign=slot_data.get("occupant_callsign"),
                            occupant_session_id=slot_data.get("occupant_session_id"),
                            is_speaking=bool(slot_data.get("is_speaking", False)),
                            active_channel=str(slot_data.get("active_channel", "")),
                        )
                    )
                squads.append(
                    SquadNode(
                        squad_id=str(squad_data["squad_id"]),
                        name=str(squad_data["name"]),
                        role_slots=role_slots,
                    )
                )
            wings.append(
                WingNode(
                    wing_id=str(wing_data["wing_id"]),
                    name=str(wing_data["name"]),
                    squads=squads,
                )
            )
        fleets.append(
            FleetNode(
                fleet_id=str(fleet_data["fleet_id"]),
                name=str(fleet_data["name"]),
                wings=wings,
            )
        )
    return FleetTreeModel(fleets=fleets)
