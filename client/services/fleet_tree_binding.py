from __future__ import annotations

from server.fleet.presence_service import apply_presence_to_tree
from shared.models.fleet_tree import FleetTreeModel, SlotPresence
from shared.models.fleet_tree_codec import decode_fleet_tree
from shared.models.fleet_tree_ids import ensure_unique_tree_ids


class FleetTreeBindingService:
    def __init__(self) -> None:
        self._model = FleetTreeModel()

    @property
    def model(self) -> FleetTreeModel:
        return self._model

    def replace_from_text(self, tree_text: str) -> FleetTreeModel:
        if not tree_text.strip():
            self._model = FleetTreeModel()
            return self._model
        self._model = ensure_unique_tree_ids(decode_fleet_tree(tree_text))
        return self._model

    def apply_presence(self, entries: list[SlotPresence]) -> FleetTreeModel:
        self._model = apply_presence_to_tree(self._model, entries)
        return self._model
