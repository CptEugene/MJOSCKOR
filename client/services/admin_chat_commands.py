from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AdminChatCommand:
    kind: Literal[
        "soundtrack_play",
        "soundtrack_stop",
        "mission_overlay",
        "video_overlay_play",
        "video_overlay_stop",
        "notice_update",
    ]
    track_id: str = ""
    video_id: str = ""
    text: str = ""
    volume_percent: int = 10
    fade_ms: int = 1200
    duration_ms: int = 3600
    color: str = "white"
    font_scale: float = 1.0
    notice_text: str = ""


def parse_admin_chat_command(text: str) -> AdminChatCommand | None:
    normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if not normalized.startswith("/"):
        return None
    command_text = normalized[1:].strip()
    if not command_text:
        return None
    command_name, _, remainder = command_text.partition(" ")
    command_name = command_name.strip().lower()
    remainder = remainder.strip()

    if command_name == "play" and remainder:
        return AdminChatCommand(kind="soundtrack_play", track_id=remainder)

    if command_name == "stop":
        return AdminChatCommand(kind="soundtrack_stop")

    if command_name == "video" and remainder:
        return AdminChatCommand(kind="video_overlay_play", video_id=remainder)

    if command_name == "stopvideo":
        return AdminChatCommand(kind="video_overlay_stop")

    if command_name in {"notice", "공지"} and remainder:
        return AdminChatCommand(kind="notice_update", notice_text=remainder)

    if command_name == "텍스트" and remainder:
        return AdminChatCommand(kind="mission_overlay", text=remainder, color="white", font_scale=1.0)

    if command_name == "텍스트g" and remainder:
        return AdminChatCommand(kind="mission_overlay", text=remainder, color="green", font_scale=2.0)

    return None
