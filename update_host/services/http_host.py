from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from update_host.services.server_registry import MaydayServerRegistry


@dataclass(frozen=True, slots=True)
class UpdateHostStatus:
    directory: Path
    bind_host: str
    port: int
    urls: tuple[str, ...]


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, registry: MaydayServerRegistry, **kwargs: object) -> None:
        self._registry = registry
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/mayday_servers.json":
            self._send_json(200, self._registry.snapshot())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/mayday/servers/heartbeat":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 16_384:
            self._send_json(400, {"ok": False, "error": "invalid_payload"})
            return
        try:
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict) or payload.get("product") != "MAYDAY":
            self._send_json(400, {"ok": False, "error": "invalid_product"})
            return
        source_ip = self.client_address[0]
        server = self._registry.heartbeat(payload, source_ip)
        self._send_json(200, {"ok": True, "server": server.to_payload()})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class CloudviewUpdateHttpHost:
    def __init__(self) -> None:
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._status: UpdateHostStatus | None = None
        self._registry = MaydayServerRegistry()

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def status(self) -> UpdateHostStatus | None:
        return self._status

    def start(self, directory: Path, port: int, bind_host: str = "0.0.0.0") -> UpdateHostStatus:
        if self.running:
            raise RuntimeError("update host is already running")
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        handler = partial(_QuietStaticHandler, directory=str(directory), registry=self._registry)
        server = ThreadingHTTPServer((bind_host, int(port)), handler)
        server.daemon_threads = True
        actual_port = int(server.server_address[1])
        thread = threading.Thread(
            target=server.serve_forever,
            name="cloudview-update-host",
            daemon=True,
        )
        thread.start()
        self._server = server
        self._thread = thread
        self._status = UpdateHostStatus(
            directory=directory,
            bind_host=bind_host,
            port=actual_port,
            urls=tuple(local_update_urls(actual_port)),
        )
        return self._status

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self._status = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=3)


def local_update_urls(port: int) -> list[str]:
    urls = [f"http://127.0.0.1:{port}/mayday_manifest.json"]
    for ip in local_ipv4_addresses():
        urls.append(f"http://{ip}:{port}/mayday_manifest.json")
    return urls


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    host_name = socket.gethostname()
    try:
        infos = socket.getaddrinfo(host_name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    for info in infos:
        ip = info[4][0]
        if ip in {"127.0.0.1", "0.0.0.0"}:
            continue
        addresses.add(ip)
    return sorted(addresses)
