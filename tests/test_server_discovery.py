from __future__ import annotations

import asyncio
import json
import socket

from client.network.server_discovery import ServerDiscoveryClient
from server.app.server_core import MaydayServerCore
from shared.constants.network import (
    DEFAULT_DISCOVERY_PORT,
    DISCOVERY_PROTOCOL,
    DISCOVERY_QUERY_PROTOCOL,
)
from shared.constants.paths import runtime_paths


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_server_discovery_accepts_mayday_broadcast() -> None:
    discovery = ServerDiscoveryClient()
    payload = {
        "protocol": DISCOVERY_PROTOCOL,
        "name": "Aegis Ops",
        "control_port": 41000,
        "players": 7,
        "requires_password": True,
        "version": "1.0.3",
        "minimum_client_version": "1.0.3",
    }

    changed = discovery._handle_packet(
        json.dumps(payload).encode("utf-8"),
        ("192.168.0.42", DEFAULT_DISCOVERY_PORT),
    )

    assert changed is True
    assert discovery.entries() == [
        {
            "name": "Aegis Ops",
            "address": "192.168.0.42",
            "control_port": 41000,
            "players": 7,
            "requires_password": True,
            "version": "1.0.3",
            "minimum_client_version": "1.0.3",
            "last_seen": discovery.entries()[0]["last_seen"],
        }
    ]


def test_server_discovery_ignores_unknown_protocol() -> None:
    discovery = ServerDiscoveryClient()
    payload = {"protocol": "other", "name": "Wrong"}

    changed = discovery._handle_packet(
        json.dumps(payload).encode("utf-8"),
        ("192.168.0.42", DEFAULT_DISCOVERY_PORT),
    )

    assert changed is False
    assert discovery.entries() == []


def test_server_discovery_accepts_registry_entry() -> None:
    discovery = ServerDiscoveryClient()
    changed = discovery._handle_registry_entry(
        {
            "name": "Registry Server",
            "address": "203.0.113.10",
            "control_port": 41000,
            "players": 5,
            "requires_password": False,
            "version": "1.0.3",
            "minimum_client_version": "1.0.3",
        }
    )

    assert changed is True
    entry = discovery.entries()[0]
    assert entry["name"] == "Registry Server"
    assert entry["address"] == "203.0.113.10"


async def _run_server_discovery_query_on_voice_port() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("127.0.0.1", 0))
    try:
        query = {
            "protocol": DISCOVERY_QUERY_PROTOCOL,
            "product": "MAYDAY",
        }
        loop = asyncio.get_running_loop()
        await loop.sock_sendto(
            sock,
            json.dumps(query).encode("utf-8"),
            ("127.0.0.1", server.voice_port),
        )
        data, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), timeout=2.0)
        return json.loads(data.decode("utf-8"))
    finally:
        sock.close()
        await server.stop()


def test_server_discovery_query_uses_voice_port() -> None:
    payload = asyncio.run(_run_server_discovery_query_on_voice_port())
    assert payload["protocol"] == DISCOVERY_PROTOCOL
    assert int(payload["control_port"]) > 0
    assert int(payload["voice_port"]) > 0
