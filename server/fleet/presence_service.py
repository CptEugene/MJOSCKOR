from __future__ import annotations

from shared.models.fleet_tree import FleetTreeModel, RoleName, SlotPresence


def apply_presence_to_tree(tree: FleetTreeModel, presences: list[SlotPresence]) -> FleetTreeModel:
    active_by_slot = {presence.slot_id: presence for presence in presences}
    for fleet in tree.fleets:
        for wing in fleet.wings:
            for squad in wing.squads:
                for slot in squad.role_slots:
                    presence = active_by_slot.get(slot.slot_id)
                    if presence is None:
                        slot.occupant_callsign = None
                        slot.occupant_session_id = None
                        slot.is_speaking = False
                        slot.active_channel = ""
                        continue
                    slot.occupant_callsign = presence.callsign
                    slot.occupant_session_id = presence.session_id
                    slot.is_speaking = presence.is_speaking
                    slot.active_channel = presence.channel_tag
                    slot.role = RoleName.coerce(presence.role)
    return tree
