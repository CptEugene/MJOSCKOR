from __future__ import annotations

import tomllib
from pathlib import Path
from uuid import uuid4

from shared.constants.app_version import APP_VERSION
from shared.constants.network import DEFAULT_SERVER_REGISTRY_HEARTBEAT_URL


class PasswordStore:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    def load(self) -> str:
        data = self._load_config()
        return str(data.get("server_password", ""))

    def load_minimum_client_version(self) -> str:
        data = self._load_config()
        return str(data.get("minimum_client_version", APP_VERSION)).strip() or APP_VERSION

    def load_server_name(self) -> str:
        data = self._load_config()
        return str(data.get("server_name", "MAYDAY Server")).strip() or "MAYDAY Server"

    def load_server_id(self) -> str:
        data = self._load_config()
        server_id = str(data.get("server_id", "")).strip()
        if server_id:
            return server_id
        server_id = uuid4().hex
        data["server_id"] = server_id
        self._save_config(data)
        return server_id

    def load_server_registry_url(self) -> str:
        data = self._load_config()
        return str(data.get("server_registry_heartbeat_url", DEFAULT_SERVER_REGISTRY_HEARTBEAT_URL)).strip()

    def load_public_host(self) -> str:
        data = self._load_config()
        return str(data.get("public_host", "")).strip()

    def load_public_control_port(self) -> int:
        data = self._load_config()
        return _int_value(data.get("public_control_port"), 0)

    def load_public_voice_port(self) -> int:
        data = self._load_config()
        return _int_value(data.get("public_voice_port"), 0)

    def save(self, password: str) -> None:
        data = self._load_config()
        data["server_password"] = password
        self._save_config(data)

    def save_minimum_client_version(self, version: str) -> None:
        data = self._load_config()
        data["minimum_client_version"] = version.strip()
        self._save_config(data)

    def save_server_name(self, server_name: str) -> None:
        data = self._load_config()
        data["server_name"] = server_name.strip() or "MAYDAY Server"
        self._save_config(data)

    def _load_config(self) -> dict[str, object]:
        if not self._config_path.exists():
            return {}
        with self._config_path.open("rb") as handle:
            return dict(tomllib.load(handle))

    def _save_config(self, data: dict[str, object]) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for key in sorted(data):
            value = data[key]
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, int | float):
                rendered = str(value)
            else:
                rendered = f'"{str(value).replace("\\", "\\\\").replace("\"", "\\\"")}"'
            lines.append(f"{key} = {rendered}")
        content = "\n".join(lines) + "\n"
        self._config_path.write_text(content, encoding="utf-8")


def _int_value(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
