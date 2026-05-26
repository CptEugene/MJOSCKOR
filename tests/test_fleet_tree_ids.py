from shared.models.fleet_tree_factory import build_default_fleet_tree
from shared.models.fleet_tree_ids import (
    compose_node_id,
    ensure_unique_tree_ids,
    next_unique_fleet_id,
    next_unique_slot_id,
    next_unique_squad_id,
    next_unique_wing_id,
)


def test_next_unique_tree_ids_are_stable_for_default_tree() -> None:
    model = build_default_fleet_tree()

    assert next_unique_fleet_id(model) == "fleet_2"
    assert next_unique_wing_id(model) == "wing_2"
    assert next_unique_squad_id(model) == "squad_3"
    assert next_unique_slot_id(model, "squad_1") == "squad_1_slot_1"


def test_ensure_unique_tree_ids_repairs_duplicate_ids() -> None:
    model = build_default_fleet_tree()
    duplicate = build_default_fleet_tree().fleets[0]
    model.fleets.append(duplicate)

    repaired = ensure_unique_tree_ids(model)

    fleet_ids = [fleet.fleet_id for fleet in repaired.fleets]
    wing_ids = [wing.wing_id for fleet in repaired.fleets for wing in fleet.wings]
    squad_ids = [squad.squad_id for fleet in repaired.fleets for wing in fleet.wings for squad in wing.squads]
    slot_ids = [
        slot.slot_id
        for fleet in repaired.fleets
        for wing in fleet.wings
        for squad in wing.squads
        for slot in squad.role_slots
    ]

    assert len(fleet_ids) == len(set(fleet_ids))
    assert len(wing_ids) == len(set(wing_ids))
    assert len(squad_ids) == len(set(squad_ids))
    assert len(slot_ids) == len(set(slot_ids))


def test_compose_node_id_includes_full_tree_path() -> None:
    assert compose_node_id("fleet_1", "wing_1", "squad_1") != compose_node_id("fleet_2", "wing_1", "squad_1")
