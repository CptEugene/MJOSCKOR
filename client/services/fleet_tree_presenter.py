from __future__ import annotations

from shared.models.fleet_tree import FleetTreeModel


def flatten_tree_for_debug(model: FleetTreeModel) -> list[str]:
    lines: list[str] = []
    for fleet in model.fleets:
        lines.append(fleet.name)
        for wing in fleet.wings:
            lines.append(f"  {wing.name}")
            for squad in wing.squads:
                lines.append(f"    {squad.name}")
                for slot in squad.role_slots:
                    lines.append(f"      {slot.display_name} [{slot.role.value}]")
    return lines

