from __future__ import annotations

from pathlib import Path

from shared.models.fleet_tree import FleetTreeModel
from shared.models.fleet_tree_codec import decode_fleet_tree, encode_fleet_tree
from shared.models.fleet_tree_factory import build_default_fleet_tree

DEFAULT_TREE_TEXT = encode_fleet_tree(build_default_fleet_tree())


class TreeStore:
    def __init__(self, tree_path: Path) -> None:
        self._tree_path = tree_path

    def load(self) -> str:
        if not self._tree_path.exists():
            return DEFAULT_TREE_TEXT
        return self._tree_path.read_text(encoding="utf-8")

    def save(self, tree_text: str) -> None:
        self._tree_path.parent.mkdir(parents=True, exist_ok=True)
        self._tree_path.write_text(tree_text, encoding="utf-8")

    def load_model(self) -> FleetTreeModel:
        return decode_fleet_tree(self.load())

    def save_model(self, model: FleetTreeModel) -> None:
        self.save(encode_fleet_tree(model))

