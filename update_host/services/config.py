from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_UPDATE_HOST_PORT = 42000


@dataclass(slots=True)
class UpdateHostConfig:
    update_dir: Path
    port: int = DEFAULT_UPDATE_HOST_PORT


def default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "cloudview_update_host.json"
    return Path(__file__).resolve().parents[2] / "runtime" / "update_host" / "cloudview_update_host.json"


def default_update_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "updates"
    return Path(__file__).resolve().parents[2] / "dist" / "release"


class UpdateHostConfigStore:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()

    def load(self) -> UpdateHostConfig:
        if not self.config_path.exists():
            return UpdateHostConfig(update_dir=default_update_dir())
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return UpdateHostConfig(update_dir=default_update_dir())
        update_dir = Path(str(data.get("update_dir", default_update_dir()))).expanduser()
        port = _normalize_port(data.get("port", DEFAULT_UPDATE_HOST_PORT))
        return UpdateHostConfig(update_dir=update_dir, port=port)

    def save(self, config: UpdateHostConfig) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {
                    "update_dir": str(config.update_dir),
                    "port": _normalize_port(config.port),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _normalize_port(value: object) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_UPDATE_HOST_PORT
    return max(1, min(65535, port))


def open_in_file_explorer(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
