from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from time import monotonic, time

from server.auth.password_store import PasswordStore
from server.fleet.tree_store import TreeStore
from server.network.session_store import ClientSession
from server.persistence.text_store import TextStore
from shared.constants.channels import CHANNEL_KEY_BY_TAG, DEFAULT_CHANNEL_ASSIGNMENTS, normalize_channel_assignments
from shared.constants.app_version import APP_VERSION
from shared.constants.network import (
    DEFAULT_CONTROL_HOST,
    DEFAULT_CONTROL_PORT,
    DEFAULT_VOICE_HOST,
    DEFAULT_VOICE_PORT,
    DISCOVERY_PROTOCOL,
    DISCOVERY_QUERY_PROTOCOL,
    SESSION_TIMEOUT_SECONDS,
)
from shared.constants.security import ADMIN_PASSWORD
from shared.protocol.messages import (
    HelloAckMessage,
    decode_control_message,
    encode_control_message,
    encode_dataclass_message,
    unpack_voice_datagram,
)
from shared.protocol.error_codes import (
    ADMIN_AUTH_REQUIRED,
    AUTH_REQUIRED,
    CLIENT_UPDATE_REQUIRED,
    INVALID_MESSAGE_TYPE,
    INVALID_PAYLOAD,
    INVALID_SERVER_PASSWORD,
    SLOT_OCCUPIED,
    SLOT_REQUIRED,
)
from shared.update.versioning import compare_versions
from shared.models.fleet_tree import ROLE_PERMISSIONS, RoleName
from shared.models.fleet_tree_codec import decode_fleet_tree, encode_fleet_tree


MEDIA_SYNC_START_DELAY_MS = 2_000


class VoiceRelayProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "MaydayServerCore") -> None:
        self._server = server
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._server.handle_discovery_datagram(data, addr):
            return
        self._server.handle_voice_datagram(data, addr)


class MaydayServerCore:
    def __init__(self, root_dir: Path, data_dir: Path, logs_dir: Path) -> None:
        self.root_dir = root_dir
        self.data_dir = data_dir
        self.logs_dir = logs_dir
        self.control_host = DEFAULT_CONTROL_HOST
        self.control_port = DEFAULT_CONTROL_PORT
        self.voice_host = DEFAULT_VOICE_HOST
        self.voice_port = DEFAULT_VOICE_PORT
        self.password_store = PasswordStore(data_dir / "server.toml")
        self.tree_store = TreeStore(data_dir / "fleet_tree.txt")
        self.kneeboard_store = TextStore(data_dir / "kneeboard.txt")
        self.notice_store = TextStore(data_dir / "notice.txt")
        self.server_name = self.password_store.load_server_name()
        self.server_id = self.password_store.load_server_id()
        self.server_password = self.password_store.load()
        self.minimum_client_version = self.password_store.load_minimum_client_version()
        self.server_registry_heartbeat_url = self.password_store.load_server_registry_url()
        self.public_host = self.password_store.load_public_host()
        self.public_control_port = self.password_store.load_public_control_port()
        self.public_voice_port = self.password_store.load_public_voice_port()
        self.tree_text = self.tree_store.load()
        self.kneeboard_text = self.kneeboard_store.load()
        self.notice_text = self.notice_store.load()
        self.sessions: dict[int, ClientSession] = {}
        self._next_session_id = 1
        self._tcp_server: asyncio.AbstractServer | None = None
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._discovery_transport: asyncio.DatagramTransport | None = None
        self._voice_receive_times: dict[int, float] = {}
        self._voice_packet_numbers: dict[int, int] = {}
        self._voice_keepalive_times: dict[int, float] = {}
        self._voice_zero_relay_log_times: dict[int, float] = {}
        self._voice_relay_log_times: dict[int, float] = {}
        self._maintenance_task: asyncio.Task[None] | None = None
        self._discovery_task: asyncio.Task[None] | None = None
        self._registry_task: asyncio.Task[None] | None = None
        self._last_registry_error = ""
        self._stopping = False
        self.log_level = "INFO"

    async def start(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._tcp_server = await asyncio.start_server(
            self._on_client_connected,
            host=self.control_host,
            port=self.control_port,
        )
        loop = asyncio.get_running_loop()
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.bind((self.voice_host, self.voice_port))
        udp_socket.setblocking(False)
        udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: VoiceRelayProtocol(self),
            sock=udp_socket,
        )
        self._udp_transport = udp_transport
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        self._discovery_task = asyncio.create_task(self._discovery_loop())
        if self.server_registry_heartbeat_url:
            self._registry_task = asyncio.create_task(self._registry_loop())
        self.info(f"listening on TCP {self.control_port}")
        self.info(f"listening on UDP {self.voice_port}")
        self.info(f"broadcasting server discovery on UDP {self.voice_port}")
        if self.server_registry_heartbeat_url:
            self.info(f"publishing server list heartbeat to {self.server_registry_heartbeat_url}")
        ips = ", ".join(self.local_ip_endpoints())
        if ips:
            self.info(f"share one of these with clients -> {ips}")

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        if self._maintenance_task is not None:
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance_task
        if self._discovery_task is not None:
            self._discovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._discovery_task
        if self._registry_task is not None:
            self._registry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._registry_task
        for session_id in list(self.sessions.keys()):
            await self.disconnect_session(session_id, announce=False)
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
        if self._udp_transport is not None:
            self._udp_transport.close()
        if self._discovery_transport is not None and self._discovery_transport is not self._udp_transport:
            self._discovery_transport.close()
        self.info("stopped")

    def status_lines(self) -> list[str]:
        return [
            f"TCP: {self.control_host}:{self.control_port}",
            f"UDP: {self.voice_host}:{self.voice_port}",
            f"Discovery: UDP {self.voice_port} (shared with voice)",
            f"Server name: {self.server_name}",
            f"Registry: {self.server_registry_heartbeat_url or 'disabled'}",
            f"Players: {self.active_client_count()}",
            f"Sessions: {len(self.sessions)}",
            f"Minimum client version: {self.minimum_client_version or APP_VERSION}",
            f"Tree path: {self.data_dir / 'fleet_tree.txt'}",
        ]

    def active_client_count(self) -> int:
        return sum(
            1
            for session in self.sessions.values()
            if session.authenticated and not session.sync_only and not session.probe_connection
        )

    def session_lines(self) -> list[str]:
        if not self.sessions:
            return ["No active sessions"]
        lines: list[str] = []
        for session in self.sessions.values():
            if not session.authenticated:
                continue
            if session.sync_only:
                continue
            lines.append(
                " | ".join(
                    [
                        f"id={session.session_id}",
                        f"callsign={session.display_name()}",
                        f"slot={session.slot_id or '-'}",
                        f"role={session.role or '-'}",
                        f"node={session.node_id or '-'}",
                        f"channel={session.channel_tag or '-'}",
                        f"ptt={'on' if session.ptt_pressed else 'off'}",
                    ]
                )
            )
        return lines

    def route_lines(self) -> list[str]:
        if not self.sessions:
            return ["No active routes"]
        lines: list[str] = []
        for session in self.sessions.values():
            if not session.authenticated:
                continue
            if session.sync_only:
                continue
            if not session.node_id:
                continue
            lines.append(
                " | ".join(
                    [
                        f"callsign={session.display_name()}",
                        f"route={session.node_id}",
                        f"channel={session.channel_tag or '-'}",
                    ]
                )
            )
        return lines or ["No active routes"]

    def local_ip_endpoints(self) -> list[str]:
        return sorted(f"{ip}:{self.control_port}" for ip in self._local_ipv4_addresses())

    def set_password(self, password: str) -> None:
        self.server_password = password
        self.password_store.save(password)
        self.info("server password updated")

    def set_minimum_client_version(self, version: str) -> None:
        normalized = version.strip()
        if not normalized:
            normalized = APP_VERSION
        self.minimum_client_version = normalized
        self.password_store.save_minimum_client_version(normalized)
        self.info(f"minimum client version updated to {normalized}")

    def set_server_name(self, server_name: str) -> None:
        normalized = " ".join(server_name.split()).strip() or "MAYDAY Server"
        self.server_name = normalized[:80]
        self.password_store.save_server_name(self.server_name)
        self.info(f"server name updated to {self.server_name}")
        self._broadcast_discovery()

    def log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        print(formatted)
        self._append_log_line(self.logs_dir / "server.log", formatted)

    def chat(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        self._append_log_line(self.logs_dir / "chat.log", formatted)

    def _append_log_line(self, log_path: Path, formatted: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(formatted + "\n")

    def debug(self, message: str) -> None:
        if self.log_level == "DEBUG":
            self.log("DEBUG", message)

    def info(self, message: str) -> None:
        self.log("INFO", message)

    def warn(self, message: str) -> None:
        self.log("WARN", message)

    def error(self, message: str) -> None:
        self.log("ERROR", message)

    async def _on_client_connected(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        session_id = self._next_session_id
        self._next_session_id += 1
        peer = writer.get_extra_info("peername")
        peer_address = peer[0] if isinstance(peer, tuple) and peer else ""
        session = ClientSession(
            session_id=session_id,
            reader=reader,
            writer=writer,
            peer_address=peer_address,
        )
        self.sessions[session_id] = session
        try:
            while not reader.at_eof():
                raw_line = await reader.readline()
                if not raw_line:
                    break
                message = decode_control_message(raw_line)
                await self._handle_control_message(session, message)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            message = str(exc)
            if "WinError 64" in message or "네트워크 이름" in message:
                pass
            else:
                self.error(f"connection error from '{session.display_identity()}' reason '{exc}'")
        finally:
            await self.disconnect_session(session_id)

    async def _handle_control_message(self, session: ClientSession, message: dict) -> None:
        message_type = str(message.get("type", ""))
        payload = message.get("payload", {}) or {}
        session.last_heartbeat = monotonic()

        if message_type == "hello":
            callsign = str(payload.get("callsign", "")).strip()
            password = str(payload.get("server_password", ""))
            sync_only = bool(payload.get("sync_only", False))
            probe_connection = bool(payload.get("probe", False)) and not sync_only
            if self.server_password and password != self.server_password:
                denied_identity = f"{callsign or f'user-{session.session_id}'} ({session.peer_address})".strip()
                self.warn(
                    f"connection denied for '{denied_identity}' reason '{INVALID_SERVER_PASSWORD}'"
                )
                await self._send(session, "error", {"reason": INVALID_SERVER_PASSWORD})
                await self.disconnect_session(session.session_id, announce=False)
                return
            client_version = str(payload.get("client_version", "")).strip()
            if self._client_update_required(client_version):
                denied_identity = f"{callsign or f'user-{session.session_id}'} ({session.peer_address})".strip()
                self.warn(
                    f"connection denied for '{denied_identity}' reason '{CLIENT_UPDATE_REQUIRED}' "
                    f"client_version '{client_version or 'missing'}' required '{self.minimum_client_version}'"
                )
                await self._send(
                    session,
                    "error",
                    {
                        "reason": CLIENT_UPDATE_REQUIRED,
                        "client_version": client_version,
                        "minimum_client_version": self.minimum_client_version,
                    },
                )
                await self.disconnect_session(session.session_id, announce=False)
                return
            session.callsign = callsign or f"user-{session.session_id}"
            session.client_version = client_version
            session.probe_connection = probe_connection
            session.sync_only = sync_only
            session.authenticated = not probe_connection
            incoming_assignments = payload.get("channel_assignments")
            if not isinstance(incoming_assignments, list):
                incoming_assignments = payload.get("channel_frequencies", DEFAULT_CHANNEL_ASSIGNMENTS)
            session.channel_assignments = normalize_channel_assignments(incoming_assignments)
            await self._send_dataclass(session, "hello_ack", HelloAckMessage(session_id=session.session_id))
            if probe_connection:
                self.info(f"CONNECTION TEST from '{session.display_identity()}' succeeded")
                return
            if sync_only:
                self.info(f"SOUNDTRACK SYNC from '{session.display_identity()}' ready")
                return
            await self._send(session, "tree_snapshot", {"tree_text": self.tree_text})
            await self._send(session, "kneeboard_snapshot", {"text": self.kneeboard_text})
            await self._send(session, "notice_snapshot", {"text": self.notice_text})
            await self.broadcast_member_snapshot()
            await self.broadcast_presence_snapshot()
            self.info(f"HELLO from '{session.display_identity()}' connected")
            return

        if not session.authenticated:
            if message_type == "heartbeat":
                return
            await self._send(session, "error", {"reason": AUTH_REQUIRED})
            self.warn(f"unauthenticated control message '{message_type}' from '{session.display_identity()}'")
            return

        if message_type == "heartbeat":
            return

        if message_type == "join_node":
            if not payload.get("slot_id") or not payload.get("node_id"):
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid join_node payload from '{session.display_name()}'")
                return
            requested_slot_id = str(payload.get("slot_id", ""))
            occupied_by_other = next(
                (
                    other
                    for other in self.sessions.values()
                    if other.session_id != session.session_id and other.slot_id == requested_slot_id
                ),
                None,
            )
            if occupied_by_other is not None:
                await self._send(session, "error", {"reason": SLOT_OCCUPIED})
                self.warn(
                    f"{session.display_identity()} failed to join slot '{requested_slot_id}' because it is occupied by '{occupied_by_other.display_identity()}'"
                )
                return
            session.fleet_id = str(payload.get("fleet_id", ""))
            session.wing_id = str(payload.get("wing_id", ""))
            session.squad_id = str(payload.get("squad_id", ""))
            session.slot_id = requested_slot_id
            session.node_id = str(payload.get("node_id", ""))
            session.role = RoleName.coerce(payload.get("role", "")).value
            await self.broadcast_presence_snapshot()
            await self.broadcast_member_snapshot()
            self.info(
                f"{session.display_identity()} joined node '{session.node_id}' role '{session.role}'"
            )
            return

        if message_type == "ptt_state":
            if not self._session_has_active_slot(session):
                session.ptt_pressed = False
                session.channel_tag = ""
                session.active_channel_number = 0
                return
            pressed = bool(payload.get("pressed", False))
            session.ptt_pressed = pressed
            session.channel_tag = str(payload.get("channel_tag", ""))
            session.active_channel_number = self._normalize_channel_number(payload.get("channel_number"))
            if pressed and not self._role_allows_channel(session.role, session.channel_tag, "tx"):
                session.ptt_pressed = False
                session.active_channel_number = 0
            await self.broadcast_presence_snapshot()
            return

        if message_type == "channel_config":
            incoming_assignments = payload.get("channel_assignments")
            if not isinstance(incoming_assignments, list):
                incoming_assignments = payload.get("channel_frequencies", [])
            if not isinstance(incoming_assignments, list) or not incoming_assignments:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid channel_config payload from '{session.display_identity()}'")
                return
            session.channel_assignments = normalize_channel_assignments(incoming_assignments)
            return

        if message_type == "chat_message":
            text = " ".join(str(payload.get("text", "")).replace("\r", " ").replace("\n", " ").split())
            if not text:
                return
            await self._broadcast_chat(
                "chat_message",
                {
                    "session_id": session.session_id,
                    "callsign": session.display_name(),
                    "role": session.role,
                    "text": text[:240],
                },
            )
            self.chat(f"{session.display_identity()}: {text[:240]}")
            return

        if message_type == "soundtrack_control":
            if not self._is_admin_payload(payload):
                await self._send(session, "error", {"reason": ADMIN_AUTH_REQUIRED})
                self.warn(f"unauthorized soundtrack_control from '{session.display_identity()}'")
                return
            command = self._normalize_soundtrack_command(payload)
            if command is None:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid soundtrack_control payload from '{session.display_identity()}'")
                return
            await self._broadcast_media_control("soundtrack_control", command)
            if command["action"] == "play":
                self.info(
                    f"SOUNDTRACK play '{command['track_id']}' requested by '{session.display_identity()}' volume {command['volume_percent']} fade {command['fade_ms']}"
                )
            else:
                self.info(f"SOUNDTRACK stop requested by '{session.display_identity()}' fade {command['fade_ms']}")
            return

        if message_type == "mission_overlay":
            if not self._is_admin_payload(payload):
                await self._send(session, "error", {"reason": ADMIN_AUTH_REQUIRED})
                self.warn(f"unauthorized mission_overlay from '{session.display_identity()}'")
                return
            command = self._normalize_mission_overlay_command(payload)
            if command is None:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid mission_overlay payload from '{session.display_identity()}'")
                return
            await self._broadcast("mission_overlay", command)
            self.info(
                f"MISSION OVERLAY '{command['text']}' requested by '{session.display_identity()}' duration {command['duration_ms']} fade {command['fade_ms']}"
            )
            return

        if message_type == "kneeboard_update":
            if not self._is_admin_payload(payload):
                await self._send(session, "error", {"reason": ADMIN_AUTH_REQUIRED})
                self.warn(f"unauthorized kneeboard_update from '{session.display_identity()}'")
                return
            text = self._normalize_kneeboard_text(payload)
            if text is None:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid kneeboard_update payload from '{session.display_identity()}'")
                return
            self.kneeboard_text = text
            self.kneeboard_store.save(text)
            await self._broadcast("kneeboard_snapshot", {"text": self.kneeboard_text})
            self.info(f"KNEEBOARD updated by '{session.display_identity()}'")
            return

        if message_type == "notice_update":
            if not self._is_admin_payload(payload):
                await self._send(session, "error", {"reason": ADMIN_AUTH_REQUIRED})
                self.warn(f"unauthorized notice_update from '{session.display_identity()}'")
                return
            text = self._normalize_notice_text(payload)
            if text is None:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid notice_update payload from '{session.display_identity()}'")
                return
            self.notice_text = text
            self.notice_store.save(text)
            await self._broadcast("notice_snapshot", {"text": self.notice_text})
            self.info(f"NOTICE updated by '{session.display_identity()}'")
            return

        if message_type == "video_overlay":
            if not self._is_admin_payload(payload):
                await self._send(session, "error", {"reason": ADMIN_AUTH_REQUIRED})
                self.warn(f"unauthorized video_overlay from '{session.display_identity()}'")
                return
            command = self._normalize_video_overlay_command(payload)
            if command is None:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid video_overlay payload from '{session.display_identity()}'")
                return
            await self._broadcast_media_control("video_overlay", command)
            if command["action"] == "play":
                self.info(
                    f"VIDEO OVERLAY play '{command['video_id']}' requested by '{session.display_identity()}' volume {command['volume_percent']}"
                )
            else:
                self.info(f"VIDEO OVERLAY stop requested by '{session.display_identity()}'")
            return

        if message_type == "tree_request":
            await self._send(session, "tree_snapshot", {"tree_text": self.tree_text})
            return

        if message_type == "tree_update":
            if not self._is_admin_payload(payload):
                await self._send(session, "error", {"reason": ADMIN_AUTH_REQUIRED})
                self.warn(f"unauthorized tree_update from '{session.display_identity()}'")
                return
            incoming_tree_text = str(payload.get("tree_text", "")).strip()
            if not incoming_tree_text:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"empty tree_update payload from '{session.display_identity()}'")
                return
            try:
                model = decode_fleet_tree(incoming_tree_text)
                normalized_tree_text = encode_fleet_tree(model)
            except Exception:
                await self._send(session, "error", {"reason": INVALID_PAYLOAD})
                self.warn(f"invalid tree_update payload from '{session.display_identity()}'")
                return
            self.tree_text = normalized_tree_text
            self.tree_store.save(self.tree_text)
            await self.broadcast_tree_snapshot()
            self.info(f"tree updated by '{session.display_identity()}'")
            return

        await self._send(session, "error", {"reason": INVALID_MESSAGE_TYPE})
        self.warn(f"unsupported message type '{message_type}' from '{session.display_identity()}'")

    def handle_voice_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            session_id, channel_tag, codec_name, packet_number, _sent_at_ms, payload = unpack_voice_datagram(data)
        except ValueError:
            return
        session = self.sessions.get(session_id)
        if session is None or not session.authenticated:
            return
        previous_udp_address = session.udp_address
        session.udp_address = addr
        if not self._session_has_active_slot(session):
            return
        if not payload:
            now = monotonic()
            last_keepalive_at = self._voice_keepalive_times.get(session_id, 0.0)
            if last_keepalive_at > 0.0:
                keepalive_gap_ms = int((now - last_keepalive_at) * 1000)
                if keepalive_gap_ms >= 5_000:
                    self.info(
                        f"VOICE DIAG keepalive gap {keepalive_gap_ms}ms from '{session.display_name()}' addr {addr}"
                    )
            self._voice_keepalive_times[session_id] = now
            if previous_udp_address is not None and previous_udp_address != addr:
                self.info(
                    f"VOICE DIAG udp endpoint changed for '{session.display_name()}' {previous_udp_address} -> {addr}"
                )
            return
        now = monotonic()
        last_receive_at = self._voice_receive_times.get(session_id, 0.0)
        if last_receive_at > 0.0:
            receive_gap_ms = int((now - last_receive_at) * 1000)
            if receive_gap_ms >= 120:
                self.info(
                    f"VOICE DIAG recv gap {receive_gap_ms}ms from '{session.display_name()}' channel '{channel_tag}' seq {packet_number}"
                )
        self._voice_receive_times[session_id] = now
        last_packet_number = self._voice_packet_numbers.get(session_id, 0)
        if packet_number > 0 and last_packet_number > 0 and packet_number > (last_packet_number + 1):
            self.info(
                f"VOICE DIAG missing {packet_number - last_packet_number - 1} packet(s) from '{session.display_name()}' last {last_packet_number} current {packet_number}"
            )
        if packet_number > 0:
            self._voice_packet_numbers[session_id] = packet_number
        session.channel_tag = channel_tag
        relay_count = 0
        relay_block_reasons: dict[str, int] = {}
        relay_destinations: list[str] = []
        for other in self.sessions.values():
            if other.session_id == session.session_id:
                continue
            if not other.authenticated:
                relay_block_reasons["dest_not_authenticated"] = relay_block_reasons.get("dest_not_authenticated", 0) + 1
                continue
            if other.udp_address is None:
                relay_block_reasons["dest_udp_missing"] = relay_block_reasons.get("dest_udp_missing", 0) + 1
                continue
            relay_reason = self.relay_block_reason(session, other)
            if relay_reason:
                relay_block_reasons[relay_reason] = relay_block_reasons.get(relay_reason, 0) + 1
                continue
            if self._udp_transport is not None:
                self._udp_transport.sendto(data, other.udp_address)
                relay_count += 1
                relay_destinations.append(
                    f"{other.display_name()}@{other.udp_address[0]}:{other.udp_address[1]}"
                )
        if relay_count <= 0:
            last_zero_relay_log_at = self._voice_zero_relay_log_times.get(session_id, 0.0)
            if (now - last_zero_relay_log_at) >= 1.0:
                self._voice_zero_relay_log_times[session_id] = now
                reason_text = ", ".join(f"{key}={value}" for key, value in sorted(relay_block_reasons.items()))
                self.info(
                    f"VOICE DIAG relayed 0 from '{session.display_name()}' channel '{channel_tag}' "
                    f"active_channel {session.active_channel_number} sessions {len(self.sessions)} reasons [{reason_text or 'none'}]"
                )
        else:
            last_relay_log_at = self._voice_relay_log_times.get(session_id, 0.0)
            if (now - last_relay_log_at) >= 1.0:
                self._voice_relay_log_times[session_id] = now
                destinations = ", ".join(relay_destinations)
                self.info(
                    f"VOICE DIAG relayed {relay_count} from '{session.display_name()}' channel '{channel_tag}' "
                    f"active_channel {session.active_channel_number} to [{destinations}]"
                )
        self.debug(
            f"VOICE from '{session.display_name()}' channel '{channel_tag}' codec '{codec_name}' seq {packet_number} bytes {len(payload)} relayed {relay_count} node '{session.node_id}'"
        )

    def handle_discovery_datagram(self, data: bytes, addr: tuple[str, int]) -> bool:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("protocol") != DISCOVERY_QUERY_PROTOCOL:
            return False
        self._send_discovery_to(addr)
        return True

    def should_relay(self, source: ClientSession, dest: ClientSession) -> bool:
        return self.relay_block_reason(source, dest) == ""

    def relay_block_reason(self, source: ClientSession, dest: ClientSession) -> str:
        if not self._session_has_active_slot(source) or not self._session_has_active_slot(dest):
            return "slot_missing"
        source_channel = (source.channel_tag or "").strip().lower()
        source_channel_number = int(source.active_channel_number or 0)
        if not source_channel or source_channel_number <= 0:
            return "source_channel_missing"
        if not self._role_allows_channel(source.role, source_channel, "tx"):
            return "source_role_channel_blocked"
        if not self._role_allows_channel(dest.role, source_channel, "rx"):
            return "dest_role_channel_blocked"
        dest_channel_number = dest.assigned_channel_for(source_channel)
        if not dest_channel_number:
            return "dest_channel_unassigned"
        if dest_channel_number != source_channel_number:
            return "channel_mismatch"
        return ""

    def _role_allows_channel(self, role: str, channel_tag: str, direction: str) -> bool:
        channel_key = CHANNEL_KEY_BY_TAG.get(channel_tag.strip().lower())
        if channel_key is None:
            return True
        permission = ROLE_PERMISSIONS[RoleName.coerce(role)].channel(channel_key)
        if direction == "tx":
            return permission.tx
        return permission.rx

    async def broadcast_presence_snapshot(self) -> None:
        by_slot: dict[str, dict] = {}
        for session in self.sessions.values():
            if not session.callsign or not session.node_id or not session.slot_id:
                continue
            if session.slot_id in by_slot:
                self.warn(
                    f"duplicate slot occupancy detected for '{session.slot_id}', keeping '{by_slot[session.slot_id]['callsign']}'"
                )
                continue
            by_slot[session.slot_id] = {
                "session_id": session.session_id,
                "callsign": session.display_name(),
                "fleet_id": session.fleet_id,
                "wing_id": session.wing_id,
                "squad_id": session.squad_id,
                "slot_id": session.slot_id,
                "node_id": session.node_id,
                "role": session.role,
                "channel_tag": session.channel_tag,
                "is_speaking": session.ptt_pressed,
            }
        snapshot = list(by_slot.values())
        await self._broadcast("presence_snapshot", {"entries": snapshot})

    async def broadcast_member_snapshot(self) -> None:
        snapshot = [
            {
                "session_id": session.session_id,
                "callsign": session.display_name(),
                "client_version": session.client_version,
                "slot_id": session.slot_id,
                "role": session.role,
            }
            for session in self.sessions.values()
            if session.authenticated and not session.sync_only and not session.probe_connection
        ]
        await self._broadcast("member_snapshot", {"entries": snapshot})

    async def broadcast_tree_snapshot(self) -> None:
        await self._broadcast("tree_snapshot", {"tree_text": self.tree_text})

    async def disconnect_session(self, session_id: int, announce: bool = True) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        self._voice_receive_times.pop(session_id, None)
        self._voice_packet_numbers.pop(session_id, None)
        self._voice_keepalive_times.pop(session_id, None)
        self._voice_zero_relay_log_times.pop(session_id, None)
        self._voice_relay_log_times.pop(session_id, None)
        try:
            session.writer.close()
            await session.writer.wait_closed()
        except Exception:
            pass
        if announce and session.probe_connection:
            self.info(f"CONNECTION TEST for '{session.display_identity()}' completed")
        elif announce and session.sync_only:
            self.info(f"SOUNDTRACK SYNC for '{session.display_identity()}' completed")
        elif announce:
            self.info(f"{session.display_identity()} disconnected")
        if session.authenticated and not session.sync_only:
            await self.broadcast_presence_snapshot()
            await self.broadcast_member_snapshot()

    async def _send(self, session: ClientSession, message_type: str, payload: dict) -> None:
        session.writer.write(encode_control_message(message_type, payload))
        await session.writer.drain()

    async def _send_dataclass(self, session: ClientSession, message_type: str, payload: object) -> None:
        session.writer.write(encode_dataclass_message(message_type, payload))
        await session.writer.drain()

    async def _broadcast(self, message_type: str, payload: dict) -> None:
        dead_sessions: list[int] = []
        for session in self.sessions.values():
            if not session.authenticated:
                continue
            if session.sync_only:
                continue
            try:
                await self._send(session, message_type, payload)
            except Exception:
                dead_sessions.append(session.session_id)
        for session_id in dead_sessions:
            await self.disconnect_session(session_id)

    async def _broadcast_chat(self, message_type: str, payload: dict) -> None:
        dead_sessions: list[int] = []
        for session in self.sessions.values():
            if not session.authenticated or session.sync_only:
                continue
            try:
                await self._send(session, message_type, payload)
            except Exception:
                dead_sessions.append(session.session_id)
        for session_id in dead_sessions:
            await self.disconnect_session(session_id)

    async def _broadcast_media_control(self, message_type: str, payload: dict) -> None:
        dead_sessions: list[int] = []
        for session in self.sessions.values():
            if not session.authenticated:
                continue
            try:
                await self._send(session, message_type, payload)
            except Exception:
                dead_sessions.append(session.session_id)
        for session_id in dead_sessions:
            await self.disconnect_session(session_id)

    def _normalize_soundtrack_command(self, payload: dict) -> dict | None:
        action = str(payload.get("action", "")).strip().lower()
        if action == "play":
            track_id = str(payload.get("track_id", "")).strip()
            if not track_id:
                return None
            now_ms = int(time() * 1000)
            start_at_ms = max(now_ms + MEDIA_SYNC_START_DELAY_MS, int(payload.get("start_at_ms", 0) or 0))
            return {
                "action": "play",
                "track_id": track_id[:255],
                "volume_percent": max(0, min(200, int(payload.get("volume_percent", 100)))),
                "fade_ms": max(0, min(10_000, int(payload.get("fade_ms", 1200)))),
                "start_at_ms": start_at_ms,
                "start_delay_ms": max(0, start_at_ms - now_ms),
            }
        if action == "stop":
            return {
                "action": "stop",
                "fade_ms": max(0, min(10_000, int(payload.get("fade_ms", 600)))),
            }
        return None

    def _normalize_mission_overlay_command(self, payload: dict) -> dict | None:
        text = " ".join(str(payload.get("text", "")).replace("\r", " ").replace("\n", " ").split())
        if not text:
            return None
        color = str(payload.get("color", "white")).strip().lower()
        if color not in {"white", "green"}:
            color = "white"
        return {
            "text": text[:180],
            "duration_ms": max(600, min(12_000, int(payload.get("duration_ms", 3600)))),
            "fade_ms": max(150, min(2_000, int(payload.get("fade_ms", 450)))),
            "color": color,
            "font_scale": max(0.8, min(3.0, float(payload.get("font_scale", 1.0)))),
        }

    def _normalize_video_overlay_command(self, payload: dict) -> dict | None:
        action = str(payload.get("action", "")).strip().lower()
        if action == "play":
            video_id = str(payload.get("video_id", "")).strip()
            if not video_id:
                return None
            now_ms = int(time() * 1000)
            start_at_ms = max(now_ms + MEDIA_SYNC_START_DELAY_MS, int(payload.get("start_at_ms", 0) or 0))
            return {
                "action": "play",
                "video_id": video_id[:255],
                "volume_percent": max(0, min(100, int(payload.get("volume_percent", 100)))),
                "start_at_ms": start_at_ms,
                "start_delay_ms": max(0, start_at_ms - now_ms),
            }
        if action == "stop":
            return {"action": "stop"}
        return None

    def _normalize_kneeboard_text(self, payload: dict) -> str | None:
        raw_text = str(payload.get("text", "")).replace("\r\n", "\n").replace("\r", "\n")
        if len(raw_text) > 8_000:
            raw_text = raw_text[:8_000]
        return raw_text

    def _normalize_notice_text(self, payload: dict) -> str | None:
        raw_text = str(payload.get("text", "")).replace("\r\n", "\n").replace("\r", "\n")
        if len(raw_text) > 2_000:
            raw_text = raw_text[:2_000]
        return raw_text

    def _is_admin_payload(self, payload: dict) -> bool:
        return str(payload.get("admin_password", "")) == ADMIN_PASSWORD

    async def _maintenance_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                now = monotonic()
                stale = [
                    session.session_id
                    for session in self.sessions.values()
                    if (now - session.last_heartbeat) > SESSION_TIMEOUT_SECONDS
                ]
                for session_id in stale:
                    await self.disconnect_session(session_id)
        except asyncio.CancelledError:
            return

    async def _discovery_loop(self) -> None:
        try:
            while True:
                self._broadcast_discovery()
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            return

    async def _registry_loop(self) -> None:
        try:
            while True:
                await self._publish_registry_heartbeat()
                await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            return

    async def _publish_registry_heartbeat(self) -> None:
        if not self.server_registry_heartbeat_url:
            return
        payload = {
            "product": "MAYDAY",
            "server_id": self.server_id,
            "name": self.server_name,
            "control_port": self.control_port,
            "voice_port": self.voice_port,
            "public_host": self.public_host,
            "public_control_port": self.public_control_port,
            "public_voice_port": self.public_voice_port,
            "players": self.active_client_count(),
            "requires_password": bool(self.server_password),
            "version": APP_VERSION,
            "minimum_client_version": self.minimum_client_version or APP_VERSION,
            "timestamp": int(time()),
        }
        try:
            await asyncio.to_thread(self._post_registry_heartbeat, payload)
            if self._last_registry_error:
                self.info("server list heartbeat restored")
            self._last_registry_error = ""
        except Exception as exc:
            error = str(exc)
            if error != self._last_registry_error:
                self.warn(f"server list heartbeat failed: {error}")
                self._last_registry_error = error

    def _post_registry_heartbeat(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.server_registry_heartbeat_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            if int(getattr(response, "status", 200)) >= 400:
                raise urllib.error.HTTPError(
                    self.server_registry_heartbeat_url,
                    int(response.status),
                    "registry heartbeat rejected",
                    response.headers,
                    None,
                )

    def _broadcast_discovery(self) -> None:
        for target in self._discovery_targets():
            self._send_discovery_to(target)

    def _send_discovery_to(self, target: tuple[str, int]) -> None:
        if self._udp_transport is None:
            return
        data = json.dumps(
            self._discovery_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with contextlib.suppress(OSError):
            self._udp_transport.sendto(data, target)

    def _discovery_payload(self) -> dict[str, object]:
        return {
            "protocol": DISCOVERY_PROTOCOL,
            "product": "MAYDAY",
            "name": self.server_name,
            "control_port": self.control_port,
            "voice_port": self.voice_port,
            "players": self.active_client_count(),
            "requires_password": bool(self.server_password),
            "version": APP_VERSION,
            "minimum_client_version": self.minimum_client_version or APP_VERSION,
            "timestamp": int(time()),
        }

    def _discovery_targets(self) -> list[tuple[str, int]]:
        targets: set[tuple[str, int]] = {("255.255.255.255", self.voice_port)}
        for ip in self._local_ipv4_addresses():
            parts = ip.split(".")
            if len(parts) == 4:
                targets.add((".".join([parts[0], parts[1], parts[2], "255"]), self.voice_port))
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

    def _session_has_active_slot(self, session: ClientSession) -> bool:
        return bool(session.slot_id and session.node_id and session.role)

    def _client_update_required(self, client_version: str) -> bool:
        if not self.minimum_client_version:
            return False
        if not client_version:
            return True
        return compare_versions(client_version, self.minimum_client_version) < 0

    def _normalize_channel_number(self, raw_value: object) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return 0
        return max(0, value)
