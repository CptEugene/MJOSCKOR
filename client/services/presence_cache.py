from __future__ import annotations

from dataclasses import dataclass, field

from client.overlay.overlay_widget import OverlayTalker


@dataclass(slots=True)
class PresenceSnapshot:
    talkers: list[OverlayTalker] = field(default_factory=list)

