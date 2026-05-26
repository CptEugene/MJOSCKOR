from __future__ import annotations

import json
import tomllib
from dataclasses import asdict
from datetime import datetime

from shared.constants.paths import runtime_paths
from shared.models.app_settings import AppSettings
from shared.constants.channels import DEFAULT_CHANNEL_ASSIGNMENTS, normalize_channel_assignments


class SettingsStore:
    def __init__(self) -> None:
        self._config_path = runtime_paths().client_config_file

    def _load_device_index(self, data: dict[str, object], key: str) -> int | None:
        raw_value = data.get(key, -1)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return None if value < 0 else value

    def load(self) -> AppSettings:
        if not self._config_path.exists():
            return AppSettings()
        try:
            with self._config_path.open("rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError:
            backup_path = self._config_path.with_suffix(
                f".broken-{datetime.now().strftime('%Y%m%d-%H%M%S')}.toml"
            )
            try:
                self._config_path.replace(backup_path)
            except OSError:
                pass
            return AppSettings()
        return AppSettings(
            nickname=str(data.get("nickname", "user")),
            server_address=str(data.get("server_address", "127.0.0.1")),
            server_password=str(data.get("server_password", "")),
            microphone_device_index=self._load_device_index(data, "microphone_device_index"),
            microphone_device_name=str(data.get("microphone_device_name", "")),
            microphone_device_endpoint_id=str(data.get("microphone_device_endpoint_id", "")),
            speaker_device_index=self._load_device_index(data, "speaker_device_index"),
            speaker_device_name=str(data.get("speaker_device_name", "")),
            speaker_device_endpoint_id=str(data.get("speaker_device_endpoint_id", "")),
            microphone_volume=int(data.get("microphone_volume", 100)),
            speaker_volume=int(data.get("speaker_volume", 100)),
            channel_assignments=normalize_channel_assignments(
                data.get("channel_assignments")
                if "channel_assignments" in data
                else data.get("channel_frequencies", DEFAULT_CHANNEL_ASSIGNMENTS)
            ),
            channel_receive_volumes=[
                int(value) for value in data.get("channel_receive_volumes", [100, 100, 100, 100])
            ],
            channel_pan_modes=[str(value) for value in data.get("channel_pan_modes", ["both", "both", "both", "both"])],
            channel_bindings=[str(value) for value in data.get("channel_bindings", ["1", "2", "3", "4"])],
            kneeboard_binding=str(data.get("kneeboard_binding", "F10")),
            overlay_chat_size=str(data.get("overlay_chat_size", "normal")),
        ).normalized()

    def save(self, settings: AppSettings) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(settings.normalized())

        def _toml_value(value: object) -> str:
            return json.dumps(value, ensure_ascii=False)

        text = "\n".join(
            [
                f'nickname = {_toml_value(payload["nickname"])}',
                f'server_address = {_toml_value(payload["server_address"])}',
                f'server_password = {_toml_value(payload["server_password"])}',
                f'microphone_device_index = {payload["microphone_device_index"] if payload["microphone_device_index"] is not None else -1}',
                f'microphone_device_name = {_toml_value(payload["microphone_device_name"])}',
                f'microphone_device_endpoint_id = {_toml_value(payload["microphone_device_endpoint_id"])}',
                f'speaker_device_index = {payload["speaker_device_index"] if payload["speaker_device_index"] is not None else -1}',
                f'speaker_device_name = {_toml_value(payload["speaker_device_name"])}',
                f'speaker_device_endpoint_id = {_toml_value(payload["speaker_device_endpoint_id"])}',
                f'microphone_volume = {payload["microphone_volume"]}',
                f'speaker_volume = {payload["speaker_volume"]}',
                f'channel_assignments = {_toml_value(payload["channel_assignments"])}',
                f'channel_receive_volumes = {_toml_value(payload["channel_receive_volumes"])}',
                f'channel_pan_modes = {_toml_value(payload["channel_pan_modes"])}',
                f'channel_bindings = {_toml_value(payload["channel_bindings"])}',
                f'kneeboard_binding = {_toml_value(payload["kneeboard_binding"])}',
                f'overlay_chat_size = {_toml_value(payload["overlay_chat_size"])}',
                "",
            ]
        )
        self._config_path.write_text(text, encoding="utf-8")
