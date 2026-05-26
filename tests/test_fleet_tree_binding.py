from client.services.fleet_tree_binding import FleetTreeBindingService
from shared.models.fleet_tree_codec import encode_fleet_tree
from shared.models.fleet_tree_factory import build_default_fleet_tree


def test_replace_from_text_normalizes_duplicate_tree_ids() -> None:
    model = build_default_fleet_tree()
    duplicate_fleet = build_default_fleet_tree().fleets[0]
    model.fleets.append(duplicate_fleet)

    binding = FleetTreeBindingService()
    normalized = binding.replace_from_text(encode_fleet_tree(model))

    fleet_ids = [fleet.fleet_id for fleet in normalized.fleets]
    wing_ids = [wing.wing_id for fleet in normalized.fleets for wing in fleet.wings]
    squad_ids = [squad.squad_id for fleet in normalized.fleets for wing in fleet.wings for squad in wing.squads]
    slot_ids = [
        slot.slot_id
        for fleet in normalized.fleets
        for wing in fleet.wings
        for squad in wing.squads
        for slot in squad.role_slots
    ]

    assert len(fleet_ids) == len(set(fleet_ids))
    assert len(wing_ids) == len(set(wing_ids))
    assert len(squad_ids) == len(set(squad_ids))
    assert len(slot_ids) == len(set(slot_ids))
