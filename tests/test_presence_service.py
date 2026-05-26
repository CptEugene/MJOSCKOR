from server.fleet.presence_service import apply_presence_to_tree
from shared.models.fleet_tree import RoleName, SlotPresence
from shared.models.fleet_tree_factory import build_default_fleet_tree


def _slot_by_id(tree, slot_id: str):
    for fleet in tree.fleets:
        for wing in fleet.wings:
            for squad in wing.squads:
                for slot in squad.role_slots:
                    if slot.slot_id == slot_id:
                        return slot
    raise AssertionError(f"slot not found: {slot_id}")


def test_presence_move_does_not_duplicate_user_across_slots() -> None:
    tree = build_default_fleet_tree()

    apply_presence_to_tree(
        tree,
        [
            SlotPresence(
                session_id=7,
                callsign="test-user",
                fleet_id="fleet_1",
                wing_id="wing_1",
                squad_id="squad_1",
                slot_id="squad_1_commander",
                role=RoleName.COMMANDER,
                channel_tag="squad",
                is_speaking=False,
            )
        ],
    )

    first_slot = _slot_by_id(tree, "squad_1_commander")
    second_slot = _slot_by_id(tree, "squad_1_officer")
    assert first_slot.occupant_callsign == "test-user"
    assert second_slot.occupant_callsign is None

    apply_presence_to_tree(
        tree,
        [
            SlotPresence(
                session_id=7,
                callsign="test-user",
                fleet_id="fleet_1",
                wing_id="wing_1",
                squad_id="squad_1",
                slot_id="squad_1_officer",
                role=RoleName.OFFICER,
                channel_tag="hq",
                is_speaking=True,
            )
        ],
    )

    first_slot = _slot_by_id(tree, "squad_1_commander")
    second_slot = _slot_by_id(tree, "squad_1_officer")
    assert first_slot.occupant_callsign is None
    assert second_slot.occupant_callsign == "test-user"
    assert second_slot.is_speaking is True
