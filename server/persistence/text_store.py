from __future__ import annotations

from pathlib import Path


class TextStore:
    def __init__(self, path: Path, default_text: str = "") -> None:
        self._path = path
        self._default_text = default_text

    def load(self) -> str:
        if not self._path.exists():
            return self._default_text
        return self._path.read_text(encoding="utf-8")

    def save(self, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(text, encoding="utf-8")
