from __future__ import annotations

from shared.models.fleet_tree import FleetTreeModel


def compose_node_id(fleet_id: str, wing_id: str, squad_id: str) -> str:
    return f"f:{fleet_id}|w:{wing_id}|s:{squad_id}"


def next_unique_fleet_id(model: FleetTreeModel) -> str:
    existing_ids = {fleet.fleet_id for fleet in model.fleets}
    return _next_unique_id(existing_ids, "fleet")


def next_unique_wing_id(model: FleetTreeModel) -> str:
    existing_ids = {wing.wing_id for fleet in model.fleets for wing in fleet.wings}
    return _next_unique_id(existing_ids, "wing")


def next_unique_squad_id(model: FleetTreeModel) -> str:
    existing_ids = {squad.squad_id for fleet in model.fleets for wing in fleet.wings for squad in wing.squads}
    return _next_unique_id(existing_ids, "squad")


def next_unique_slot_id(model: FleetTreeModel, squad_id: str) -> str:
    existing_ids = {
        slot.slot_id
        for fleet in model.fleets
        for wing in fleet.wings
        for squad in wing.squads
        for slot in squad.role_slots
    }
    index = 1
    while True:
        candidate = f"{squad_id}_slot_{index}"
        if candidate not in existing_ids:
            return candidate
        index += 1


def ensure_unique_tree_ids(model: FleetTreeModel) -> FleetTreeModel:
    seen_fleets: set[str] = set()
    seen_wings: set[str] = set()
    seen_squads: set[str] = set()
    seen_slots: set[str] = set()

    for fleet in model.fleets:
        if not fleet.fleet_id or fleet.fleet_id in seen_fleets:
            fleet.fleet_id = _next_unique_id(seen_fleets, "fleet")
        seen_fleets.add(fleet.fleet_id)
        for wing in fleet.wings:
            if not wing.wing_id or wing.wing_id in seen_wings:
                wing.wing_id = _next_unique_id(seen_wings, "wing")
            seen_wings.add(wing.wing_id)
            for squad in wing.squads:
                if not squad.squad_id or squad.squad_id in seen_squads:
                    squad.squad_id = _next_unique_id(seen_squads, "squad")
                seen_squads.add(squad.squad_id)
                slot_index = 1
                for slot in squad.role_slots:
                    while True:
                        fallback_slot_id = f"{squad.squad_id}_slot_{slot_index}"
                        slot_index += 1
                        if fallback_slot_id not in seen_slots:
                            break
                    if not slot.slot_id or slot.slot_id in seen_slots:
                        slot.slot_id = fallback_slot_id
                    seen_slots.add(slot.slot_id)
    return model


def _next_unique_id(existing_ids: set[str], prefix: str) -> str:
    index = 1
    while True:
        candidate = f"{prefix}_{index}"
        if candidate not in existing_ids:
            return candidate
        index += 1
