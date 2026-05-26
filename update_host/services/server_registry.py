from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any


SERVER_REGISTRY_TTL_SECONDS = 45


@dataclass(slots=True)
class RegisteredMaydayServer:
    server_id: str
    name: str
    address: str
    control_port: int
    voice_port: int
    players: int
    requires_password: bool
    version: str
    minimum_client_version: str
    last_seen: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "name": self.name,
            "address": self.address,
            "control_port": self.control_port,
            "voice_port": self.voice_port,
            "players": self.players,
            "requires_password": self.requires_password,
            "version": self.version,
            "minimum_client_version": self.minimum_client_version,
            "last_seen": int(self.last_seen),
        }


class MaydayServerRegistry:
    def __init__(self, *, ttl_seconds: int = SERVER_REGISTRY_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._servers: dict[str, RegisteredMaydayServer] = {}

    def heartbeat(self, payload: dict[str, Any], source_ip: str) -> RegisteredMaydayServer:
        now = time()
        server_id = str(payload.get("server_id", "")).strip()
        if not server_id:
            server_id = f"{source_ip}:{_int_value(payload.get('control_port'), 41000)}"
        public_host = str(payload.get("public_host", "")).strip()
        address = public_host or source_ip
        control_port = _int_value(
            payload.get("public_control_port") or payload.get("control_port"),
            41000,
        )
        voice_port = _int_value(
            payload.get("public_voice_port") or payload.get("voice_port"),
            41001,
        )
        server = RegisteredMaydayServer(
            server_id=server_id[:120],
            name=(str(payload.get("name", "MAYDAY Server")).strip() or "MAYDAY Server")[:80],
            address=address[:255],
            control_port=control_port,
            voice_port=voice_port,
            players=max(0, _int_value(payload.get("players"), 0)),
            requires_password=bool(payload.get("requires_password", False)),
            version=str(payload.get("version", ""))[:40],
            minimum_client_version=str(payload.get("minimum_client_version", ""))[:40],
            last_seen=now,
        )
        self._servers[server.server_id] = server
        self._remove_stale(now)
        return server

    def snapshot(self) -> dict[str, Any]:
        now = time()
        self._remove_stale(now)
        servers = sorted(
            self._servers.values(),
            key=lambda server: (server.name.lower(), server.address, server.control_port),
        )
        return {
            "product": "MAYDAY",
            "ttl_seconds": self._ttl_seconds,
            "servers": [server.to_payload() for server in servers],
            "generated_at": int(now),
        }

    def _remove_stale(self, now: float) -> None:
        stale_ids = [
            server_id
            for server_id, server in self._servers.items()
            if (now - server.last_seen) > self._ttl_seconds
        ]
        for server_id in stale_ids:
            self._servers.pop(server_id, None)


def _int_value(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
