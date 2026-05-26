from __future__ import annotations

from dataclasses import dataclass, field

from shared.constants.channels import DEFAULT_CHANNEL_ASSIGNMENTS, normalize_channel_assignments


@dataclass(slots=True)
class AppSettings:
    nickname: str = "user"
    server_address: str = "127.0.0.1"
    server_password: str = ""
    microphone_device_index: int | None = None
    microphone_device_name: str = ""
    microphone_device_endpoint_id: str = ""
    speaker_device_index: int | None = None
    speaker_device_name: str = ""
    speaker_device_endpoint_id: str = ""
    microphone_volume: int = 100
    speaker_volume: int = 100
    channel_assignments: list[int] = field(default_factory=lambda: list(DEFAULT_CHANNEL_ASSIGNMENTS))
    channel_receive_volumes: list[int] = field(default_factory=lambda: [100, 100, 100, 100])
    channel_pan_modes: list[str] = field(default_factory=lambda: ["both", "both", "both", "both"])
    channel_bindings: list[str] = field(default_factory=lambda: ["1", "2", "3", "4"])
    kneeboard_binding: str = "F10"
    overlay_chat_size: str = "normal"

    def normalized(self) -> "AppSettings":
        def _pad_strings(values: list[str], defaults: list[str]) -> list[str]:
            result = [str(value) for value in values[: len(defaults)]]
            while len(result) < len(defaults):
                result.append(defaults[len(result)])
            return result

        def _pad_ints(values: list[int], defaults: list[int]) -> list[int]:
            result = [int(value) for value in values[: len(defaults)]]
            while len(result) < len(defaults):
                result.append(defaults[len(result)])
            return result

        return AppSettings(
            nickname=str(self.nickname or "user"),
            server_address=str(self.server_address or "127.0.0.1"),
            server_password=str(self.server_password or ""),
            microphone_device_index=self.microphone_device_index,
            microphone_device_name=str(self.microphone_device_name or "").strip(),
            microphone_device_endpoint_id=str(self.microphone_device_endpoint_id or "").strip(),
            speaker_device_index=self.speaker_device_index,
            speaker_device_name=str(self.speaker_device_name or "").strip(),
            speaker_device_endpoint_id=str(self.speaker_device_endpoint_id or "").strip(),
            microphone_volume=max(0, min(200, int(self.microphone_volume))),
            speaker_volume=max(0, min(200, int(self.speaker_volume))),
            channel_assignments=normalize_channel_assignments(self.channel_assignments),
            channel_receive_volumes=_pad_ints(self.channel_receive_volumes, [100, 100, 100, 100]),
            channel_pan_modes=_pad_strings(self.channel_pan_modes, ["both", "both", "both", "both"]),
            channel_bindings=_pad_strings(self.channel_bindings, ["1", "2", "3", "4"]),
            kneeboard_binding=str(self.kneeboard_binding or "F10"),
            overlay_chat_size=_normalize_overlay_chat_size(self.overlay_chat_size),
        )


def _normalize_overlay_chat_size(raw_value: object) -> str:
    normalized = str(raw_value or "normal").strip().lower()
    if normalized in {"small", "normal", "large"}:
        return normalized
    return "normal"
