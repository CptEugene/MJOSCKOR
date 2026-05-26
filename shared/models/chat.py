from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChatMessage:
    session_id: int
    callsign: str
    text: str
    role: str = ""
