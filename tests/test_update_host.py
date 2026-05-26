from __future__ import annotations

import json
import socket
import urllib.request

from update_host.services.config import DEFAULT_UPDATE_HOST_PORT, UpdateHostConfigStore
from update_host.services.http_host import CloudviewUpdateHttpHost, local_update_urls


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_update_host_serves_manifest(tmp_path) -> None:
    update_dir = tmp_path / "updates"
    update_dir.mkdir()
    (update_dir / "mayday_manifest.json").write_text(
        json.dumps({"product": "MAYDAY", "latest_version": "1.0.2"}),
        encoding="utf-8",
    )
    host = CloudviewUpdateHttpHost()
    status = host.start(update_dir, _free_port(), bind_host="127.0.0.1")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{status.port}/mayday_manifest.json") as response:
            data = json.loads(response.read().decode("utf-8"))
    finally:
        host.stop()

    assert data["product"] == "MAYDAY"
    assert not host.running


def test_update_host_serves_mayday_server_registry(tmp_path) -> None:
    update_dir = tmp_path / "updates"
    host = CloudviewUpdateHttpHost()
    status = host.start(update_dir, _free_port(), bind_host="127.0.0.1")
    heartbeat = {
        "product": "MAYDAY",
        "server_id": "server-1",
        "name": "Public Ops",
        "control_port": 41000,
        "voice_port": 41001,
        "players": 3,
        "requires_password": True,
        "version": "1.0.3",
        "minimum_client_version": "1.0.3",
    }
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{status.port}/api/mayday/servers/heartbeat",
            data=json.dumps(heartbeat).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            accepted = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(f"http://127.0.0.1:{status.port}/mayday_servers.json") as response:
            registry = json.loads(response.read().decode("utf-8"))
    finally:
        host.stop()

    assert accepted["ok"] is True
    assert registry["product"] == "MAYDAY"
    assert registry["servers"][0]["name"] == "Public Ops"
    assert registry["servers"][0]["address"] == "127.0.0.1"


def test_update_host_config_store_roundtrip(tmp_path) -> None:
    store = UpdateHostConfigStore(tmp_path / "host.json")
    config = store.load()
    assert config.port == DEFAULT_UPDATE_HOST_PORT

    config.update_dir = tmp_path / "files"
    config.port = 42001
    store.save(config)

    reloaded = store.load()
    assert reloaded.update_dir == tmp_path / "files"
    assert reloaded.port == 42001


def test_local_update_urls_include_manifest_path() -> None:
    urls = local_update_urls(42000)
    assert "http://127.0.0.1:42000/mayday_manifest.json" in urls
