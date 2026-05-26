from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from shared.constants.channels import DEFAULT_CHANNEL_ASSIGNMENTS, channel_assignment_for_tag, normalize_channel_assignments


@dataclass(slots=True)
class ClientSession:
    session_id: int
    reader: Any
    writer: Any
    peer_address: str = ""
    callsign: str = ""
    client_version: str = ""
    fleet_id: str = ""
    wing_id: str = ""
    squad_id: str = ""
    slot_id: str = ""
    node_id: str = ""
    role: str = ""
    channel_tag: str = ""
    channel_assignments: list[int] = field(default_factory=lambda: list(DEFAULT_CHANNEL_ASSIGNMENTS))
    active_channel_number: int = 0
    ptt_pressed: bool = False
    udp_address: tuple[str, int] | None = None
    last_heartbeat: float = field(default_factory=monotonic)
    authenticated: bool = False
    probe_connection: bool = False
    sync_only: bool = False

    def display_name(self) -> str:
        return self.callsign or f"session-{self.session_id}"

    def display_identity(self) -> str:
        if self.peer_address:
            return f"{self.display_name()} ({self.peer_address})"
        return self.display_name()

    def assigned_channel_for(self, channel_tag: str) -> int:
        return channel_assignment_for_tag(normalize_channel_assignments(self.channel_assignments), channel_tag)
