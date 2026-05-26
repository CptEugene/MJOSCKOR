from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import threading
import time
import urllib.request
from typing import Callable

from shared.constants.network import (
    DEFAULT_CONTROL_PORT,
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_SERVER_REGISTRY_LIST_URL,
    DISCOVERY_PROTOCOL,
    DISCOVERY_QUERY_PROTOCOL,
)


@dataclass(frozen=True, slots=True)
class DiscoveredServer:
    name: str
    address: str
    control_port: int
    players: int
    requires_password: bool
    version: str
    minimum_client_version: str
    last_seen: float

    def to_ui_entry(self) -> dict[str, object]:
        return {
            "name": self.name,
            "address": self.address,
            "control_port": self.control_port,
            "players": self.players,
            "requires_password": self.requires_password,
            "version": self.version,
            "minimum_client_version": self.minimum_client_version,
            "last_seen": self.last_seen,
        }


class ServerDiscoveryClient:
    def __init__(
        self,
        *,
        port: int = DEFAULT_DISCOVERY_PORT,
        stale_after_seconds: float = 20.0,
        registry_url: str = DEFAULT_SERVER_REGISTRY_LIST_URL,
    ) -> None:
        self._port = port
        self._registry_url = registry_url.strip()
        self._stale_after_seconds = stale_after_seconds
        self._servers: dict[tuple[str, int], DiscoveredServer] = {}
        self._callbacks: list[Callable[[list[dict[str, object]]], None]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._probe_interval_seconds = 2.0
        self._registry_poll_interval_seconds = 5.0

    def on_changed(self, callback: Callable[[list[dict[str, object]]], None]) -> None:
        self._callbacks.append(callback)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="MaydayServerDiscovery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None

    def entries(self) -> list[dict[str, object]]:
        with self._lock:
            return [server.to_ui_entry() for server in self._sorted_servers_locked()]

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self._port))
            sock.settimeout(0.5)
            last_probe_at = 0.0
            last_registry_poll_at = 0.0
            while not self._stop_event.is_set():
                now = time.monotonic()
                if (now - last_probe_at) >= self._probe_interval_seconds:
                    self._send_probe(sock)
                    last_probe_at = now
                if self._registry_url and (now - last_registry_poll_at) >= self._registry_poll_interval_seconds:
                    if self._fetch_registry():
                        self._emit_changed()
                    last_registry_poll_at = now
                changed = self._remove_stale_servers()
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    if changed:
                        self._emit_changed()
                    continue
                except OSError:
                    break
                if self._handle_packet(data, addr):
                    self._emit_changed()
                elif changed:
                    self._emit_changed()
        finally:
            sock.close()

    def _handle_packet(self, data: bytes, addr: tuple[str, int]) -> bool:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("protocol") != DISCOVERY_PROTOCOL:
            return False
        address = addr[0]
        control_port = self._int_value(payload.get("control_port"), DEFAULT_CONTROL_PORT)
        server = DiscoveredServer(
            name=str(payload.get("name", "MAYDAY Server")).strip() or "MAYDAY Server",
            address=address,
            control_port=control_port,
            players=max(0, self._int_value(payload.get("players"), 0)),
            requires_password=bool(payload.get("requires_password", False)),
            version=str(payload.get("version", "")),
            minimum_client_version=str(payload.get("minimum_client_version", "")),
            last_seen=time.monotonic(),
        )
        key = (server.address, server.control_port)
        with self._lock:
            previous = self._servers.get(key)
            self._servers[key] = server
        return previous != server

    def _remove_stale_servers(self) -> bool:
        now = time.monotonic()
        with self._lock:
            stale_keys = [
                key
                for key, server in self._servers.items()
                if (now - server.last_seen) > self._stale_after_seconds
            ]
            for key in stale_keys:
                self._servers.pop(key, None)
        return bool(stale_keys)

    def _fetch_registry(self) -> bool:
        try:
            with urllib.request.urlopen(self._registry_url, timeout=3.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict) or payload.get("product") != "MAYDAY":
            return False
        servers = payload.get("servers", [])
        if not isinstance(servers, list):
            return False
        changed = False
        for entry in servers:
            if isinstance(entry, dict) and self._handle_registry_entry(entry):
                changed = True
        return changed

    def _handle_registry_entry(self, payload: dict[str, object]) -> bool:
        address = str(payload.get("address", "")).strip()
        if not address:
            return False
        control_port = self._int_value(payload.get("control_port"), DEFAULT_CONTROL_PORT)
        server = DiscoveredServer(
            name=str(payload.get("name", "MAYDAY Server")).strip() or "MAYDAY Server",
            address=address,
            control_port=control_port,
            players=max(0, self._int_value(payload.get("players"), 0)),
            requires_password=bool(payload.get("requires_password", False)),
            version=str(payload.get("version", "")),
            minimum_client_version=str(payload.get("minimum_client_version", "")),
            last_seen=time.monotonic(),
        )
        key = (server.address, server.control_port)
        with self._lock:
            previous = self._servers.get(key)
            self._servers[key] = server
        return previous != server

    def _send_probe(self, sock: socket.socket) -> None:
        payload = {
            "protocol": DISCOVERY_QUERY_PROTOCOL,
            "product": "MAYDAY",
            "timestamp": int(time.time()),
        }
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        for target in self._discovery_targets():
            try:
                sock.sendto(data, target)
            except OSError:
                continue

    def _discovery_targets(self) -> list[tuple[str, int]]:
        targets: set[tuple[str, int]] = {("255.255.255.255", self._port)}
        for ip in self._local_ipv4_addresses():
            parts = ip.split(".")
            if len(parts) == 4:
                targets.add((".".join([parts[0], parts[1], parts[2], "255"]), self._port))
        return sorted(targets)

    @staticmethod
    def _local_ipv4_addresses() -> set[str]:
        addresses: set[str] = set()
        try:
            host_name = socket.gethostname()
            infos = socket.getaddrinfo(host_name, None, family=socket.AF_INET, type=socket.SOCK_DGRAM)
        except OSError:
            return addresses
        for info in infos:
            ip = info[4][0]
            if ip in {"127.0.0.1", "0.0.0.0"}:
                continue
            addresses.add(ip)
        return addresses

    def _emit_changed(self) -> None:
        entries = self.entries()
        for callback in list(self._callbacks):
            callback(entries)

    def _sorted_servers_locked(self) -> list[DiscoveredServer]:
        return sorted(self._servers.values(), key=lambda server: (server.name.lower(), server.address))

    @staticmethod
    def _int_value(value: object, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback
