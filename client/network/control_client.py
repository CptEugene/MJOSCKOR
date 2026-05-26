from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
from time import monotonic
from collections.abc import Callable
from dataclasses import dataclass, field

from shared.constants.channels import DEFAULT_CHANNEL_ASSIGNMENTS, channel_assignment_for_tag, normalize_channel_assignments
from shared.constants.app_version import APP_VERSION
from shared.models.chat import ChatMessage
from shared.models.fleet_tree import RoleName, SlotPresence
from shared.protocol.messages import decode_control_message, encode_control_message


@dataclass(slots=True)
class ControlClientState:
    connected: bool = False
    connecting: bool = False
    callsign: str = "user"
    server_address: str = "127.0.0.1"
    server_password: str = ""
    admin_password: str = ""
    session_id: int = 0
    selected_node_id: str = ""
    selected_role: str = ""
    selected_channel_tag: str = "general"
    channel_assignments: list[int] = field(default_factory=lambda: list(DEFAULT_CHANNEL_ASSIGNMENTS))
    tree_text: str = ""
    kneeboard_text: str = ""
    notice_text: str = ""
    last_error: str = ""
    presence_entries: list[SlotPresence] = field(default_factory=list)
    member_entries: list[dict[str, object]] = field(default_factory=list)
    chat_entries: list[ChatMessage] = field(default_factory=list)


class ControlClient:
    def __init__(self) -> None:
        self.state = ControlClientState()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mayday-control-client")
        self._thread.start()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._callbacks: dict[str, list[Callable[[], None]]] = {
            "state": [],
            "tree": [],
            "presence": [],
            "chat": [],
            "kneeboard": [],
            "notice": [],
            "members": [],
        }
        self._soundtrack_callbacks: list[Callable[[dict], None]] = []
        self._mission_overlay_callbacks: list[Callable[[dict], None]] = []
        self._video_overlay_callbacks: list[Callable[[dict], None]] = []

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def close(self) -> None:
        future = asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)
        future.result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def on_state_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["state"].append(callback)

    def on_tree_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["tree"].append(callback)

    def on_presence_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["presence"].append(callback)

    def on_chat_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["chat"].append(callback)

    def on_kneeboard_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["kneeboard"].append(callback)

    def on_notice_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["notice"].append(callback)

    def on_members_changed(self, callback: Callable[[], None]) -> None:
        self._callbacks["members"].append(callback)

    def on_soundtrack_command(self, callback: Callable[[dict], None]) -> None:
        self._soundtrack_callbacks.append(callback)

    def on_mission_overlay_command(self, callback: Callable[[dict], None]) -> None:
        self._mission_overlay_callbacks.append(callback)

    def on_video_overlay_command(self, callback: Callable[[dict], None]) -> None:
        self._video_overlay_callbacks.append(callback)

    def configure(
        self,
        *,
        callsign: str,
        server_address: str,
        server_password: str,
        channel_assignments: list[int] | None = None,
    ) -> None:
        self.state.callsign = callsign
        self.state.server_address = server_address
        self.state.server_password = server_password
        if channel_assignments is not None:
            self.state.channel_assignments = normalize_channel_assignments(channel_assignments)
        self._emit("state")

    def connect(self) -> None:
        asyncio.run_coroutine_threadsafe(self._connect(), self._loop)

    def disconnect(self) -> None:
        asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

    def request_tree(self) -> None:
        asyncio.run_coroutine_threadsafe(self._send("tree_request", {}), self._loop)

    def update_tree(self, tree_text: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._send(
                "tree_update",
                {"tree_text": tree_text, "admin_password": self.state.admin_password},
            ),
            self._loop,
        )

    def join_slot(
        self,
        *,
        fleet_id: str,
        wing_id: str,
        squad_id: str,
        slot_id: str,
        node_id: str,
        role: str,
    ) -> None:
        self.clear_last_error()
        asyncio.run_coroutine_threadsafe(
            self._send(
                "join_node",
                {
                    "fleet_id": fleet_id,
                    "wing_id": wing_id,
                    "squad_id": squad_id,
                    "slot_id": slot_id,
                    "node_id": node_id,
                    "role": role,
                },
            ),
            self._loop,
        )

    def set_admin_password(self, password: str) -> None:
        self.state.admin_password = password

    def clear_last_error(self) -> None:
        self.state.last_error = ""

    def set_ptt_state(self, pressed: bool, channel_tag: str) -> None:
        self.state.selected_channel_tag = channel_tag
        channel_number = self._channel_assignment_for(channel_tag)
        asyncio.run_coroutine_threadsafe(
            self._send(
                "ptt_state",
                {"pressed": pressed, "channel_tag": channel_tag, "channel_number": channel_number},
            ),
            self._loop,
        )

    def update_channel_assignments(self, channel_assignments: list[int]) -> None:
        self.state.channel_assignments = normalize_channel_assignments(channel_assignments)
        asyncio.run_coroutine_threadsafe(
            self._send("channel_config", {"channel_assignments": self.state.channel_assignments}),
            self._loop,
        )

    def send_chat(self, text: str) -> None:
        normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if not normalized:
            return
        asyncio.run_coroutine_threadsafe(
            self._send("chat_message", {"text": normalized[:240]}),
            self._loop,
        )

    def send_kneeboard_update(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        asyncio.run_coroutine_threadsafe(
            self._send(
                "kneeboard_update",
                {
                    "text": normalized[:8000],
                    "admin_password": self.state.admin_password,
                },
            ),
            self._loop,
        )

    def send_notice_update(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        asyncio.run_coroutine_threadsafe(
            self._send(
                "notice_update",
                {
                    "text": normalized[:2000],
                    "admin_password": self.state.admin_password,
                },
            ),
            self._loop,
        )

    def send_soundtrack_play(self, track_id: str, volume_percent: int = 10, fade_ms: int = 1200) -> None:
        normalized_track_id = track_id.strip()
        if not normalized_track_id:
            return
        asyncio.run_coroutine_threadsafe(
            self._send(
                "soundtrack_control",
                {
                    "action": "play",
                    "track_id": normalized_track_id,
                    "admin_password": self.state.admin_password,
                    "volume_percent": max(0, min(200, int(volume_percent))),
                    "fade_ms": max(0, min(10_000, int(fade_ms))),
                },
            ),
            self._loop,
        )

    def send_soundtrack_stop(self, fade_ms: int = 600) -> None:
        asyncio.run_coroutine_threadsafe(
            self._send(
                "soundtrack_control",
                {
                    "action": "stop",
                    "admin_password": self.state.admin_password,
                    "fade_ms": max(0, min(10_000, int(fade_ms))),
                },
            ),
            self._loop,
        )

    def send_mission_overlay(
        self,
        text: str,
        duration_ms: int = 3600,
        fade_ms: int = 450,
        *,
        color: str = "white",
        font_scale: float = 1.0,
    ) -> None:
        normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if not normalized:
            return
        asyncio.run_coroutine_threadsafe(
            self._send(
                "mission_overlay",
                {
                    "text": normalized[:180],
                    "admin_password": self.state.admin_password,
                    "duration_ms": max(600, min(12_000, int(duration_ms))),
                    "fade_ms": max(150, min(2_000, int(fade_ms))),
                    "color": str(color).strip().lower() or "white",
                    "font_scale": max(0.8, min(3.0, float(font_scale))),
                },
            ),
            self._loop,
        )

    def send_video_overlay_play(self, video_id: str, volume_percent: int = 10) -> None:
        normalized_video_id = video_id.strip()
        if not normalized_video_id:
            return
        asyncio.run_coroutine_threadsafe(
            self._send(
                "video_overlay",
                {
                    "action": "play",
                    "video_id": normalized_video_id,
                    "admin_password": self.state.admin_password,
                    "volume_percent": max(0, min(100, int(volume_percent))),
                },
            ),
            self._loop,
        )

    def send_video_overlay_stop(self) -> None:
        asyncio.run_coroutine_threadsafe(
            self._send(
                "video_overlay",
                {
                    "action": "stop",
                    "admin_password": self.state.admin_password,
                },
            ),
            self._loop,
        )

    async def connect_test(
        self,
        callsign: str,
        server_address: str,
        server_password: str,
        port: int = 41000,
    ) -> tuple[bool, str]:
        writer = None
        try:
            reader, writer = await asyncio.open_connection(server_address, port)
            writer.write(
                encode_control_message(
                    "hello",
                    {
                        "callsign": callsign,
                        "server_password": server_password,
                        "probe": True,
                        "client_version": APP_VERSION,
                    },
                )
            )
            await writer.drain()
            deadline = monotonic() + 3.0
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False, "no_response"
                first = await asyncio.wait_for(reader.readline(), timeout=remaining)
                if not first:
                    return False, "no_response"
                message = decode_control_message(first)
                if message.get("type") == "error":
                    return False, str(message.get("payload", {}).get("reason", "unknown_error"))
                if message.get("type") == "hello_ack":
                    return True, "connected"
        except TimeoutError:
            return False, "no_response"
        except socket.gaierror:
            return False, "invalid_server_address"
        except ConnectionRefusedError:
            return False, "server_unreachable"
        except OSError:
            return False, "server_unreachable"
        except Exception as exc:
            return False, str(exc)
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    def _emit(self, key: str) -> None:
        for callback in self._callbacks.get(key, []):
            callback()

    async def _connect(self) -> None:
        await self._disconnect()
        self.state.connecting = True
        self.state.last_error = ""
        self._emit("state")
        try:
            self._reader, self._writer = await asyncio.open_connection(self.state.server_address, 41000)
            await self._send(
                "hello",
                {
                    "callsign": self.state.callsign,
                    "server_password": self.state.server_password,
                    "client_version": APP_VERSION,
                    "channel_assignments": self.state.channel_assignments,
                },
            )
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._listen_task = asyncio.create_task(self._listen_loop())
        except Exception as exc:
            self.state.connected = False
            self.state.connecting = False
            self.state.last_error = str(exc)
            self._emit("state")

    async def _disconnect(self) -> None:
        for task in (self._heartbeat_task, self._listen_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._heartbeat_task = None
        self._listen_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._reader = None
        self._writer = None
        self.state.connected = False
        self.state.connecting = False
        self.state.session_id = 0
        self.state.selected_node_id = ""
        self.state.selected_role = ""
        self.state.selected_channel_tag = "general"
        self.state.tree_text = ""
        self.state.kneeboard_text = ""
        self.state.notice_text = ""
        self.state.presence_entries = []
        self.state.member_entries = []
        self.state.chat_entries = []
        self.state.admin_password = ""
        self._emit("state")
        self._emit("tree")
        self._emit("presence")
        self._emit("chat")
        self._emit("kneeboard")
        self._emit("notice")
        self._emit("members")

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(2.0)
                await self._send("heartbeat", {})
        except asyncio.CancelledError:
            return

    async def _listen_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                raw_line = await self._reader.readline()
                if not raw_line:
                    raise ConnectionError("server_closed")
                await self._handle_message(decode_control_message(raw_line))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.state.last_error = str(exc)
            self._emit("state")
            await self._disconnect()

    async def _handle_message(self, message: dict) -> None:
        message_type = str(message.get("type", ""))
        payload = message.get("payload", {}) or {}
        if message_type == "hello_ack":
            self.state.session_id = int(payload.get("session_id", 0))
            self.state.connected = True
            self.state.connecting = False
            self._emit("state")
            await self._send("tree_request", {})
            return
        if message_type == "tree_snapshot":
            self.state.tree_text = str(payload.get("tree_text", ""))
            self._emit("tree")
            return
        if message_type == "kneeboard_snapshot":
            self.state.kneeboard_text = str(payload.get("text", ""))
            self._emit("kneeboard")
            return
        if message_type == "notice_snapshot":
            self.state.notice_text = str(payload.get("text", ""))
            self._emit("notice")
            return
        if message_type == "member_snapshot":
            entries: list[dict[str, object]] = []
            for item in payload.get("entries", []):
                if not isinstance(item, dict):
                    continue
                entries.append(
                    {
                        "session_id": int(item.get("session_id", 0)),
                        "callsign": str(item.get("callsign", "")),
                        "client_version": str(item.get("client_version", "")),
                        "slot_id": str(item.get("slot_id", "")),
                        "role": str(item.get("role", "")),
                    }
                )
            self.state.member_entries = entries
            self._emit("members")
            return
        if message_type == "presence_snapshot":
            entries: list[SlotPresence] = []
            for item in payload.get("entries", []):
                role = RoleName.coerce(item.get("role", "Soldier"))
                entries.append(
                    SlotPresence(
                        session_id=int(item.get("session_id", 0)),
                        callsign=str(item.get("callsign", "")),
                        fleet_id=str(item.get("fleet_id", "")),
                        wing_id=str(item.get("wing_id", "")),
                        squad_id=str(item.get("squad_id", "")),
                        slot_id=str(item.get("slot_id", "")),
                        role=role,
                        channel_tag=str(item.get("channel_tag", "")),
                        is_speaking=bool(item.get("is_speaking", False)),
                    )
                )
            self.state.presence_entries = entries
            self._emit("presence")
            return
        if message_type == "error":
            self.state.last_error = str(payload.get("reason", "unknown_error"))
            self._emit("state")
            return
        if message_type == "chat_message":
            text = " ".join(str(payload.get("text", "")).replace("\r", " ").replace("\n", " ").split())
            if not text:
                return
            self._append_chat_message(
                ChatMessage(
                    session_id=int(payload.get("session_id", 0)),
                    callsign=str(payload.get("callsign", "")),
                    role=str(payload.get("role", "")),
                    text=text,
                )
            )
            self._emit("chat")
            return
        if message_type == "soundtrack_control":
            command = dict(payload)
            for callback in self._soundtrack_callbacks:
                callback(command)
            return
        if message_type == "mission_overlay":
            command = dict(payload)
            for callback in self._mission_overlay_callbacks:
                callback(command)
            return
        if message_type == "video_overlay":
            command = dict(payload)
            for callback in self._video_overlay_callbacks:
                callback(command)
            return

    async def _send(self, message_type: str, payload: dict) -> None:
        if self._writer is None:
            return
        self._writer.write(encode_control_message(message_type, payload))
        await self._writer.drain()

    def _append_chat_message(self, message: ChatMessage) -> None:
        self.state.chat_entries = [*self.state.chat_entries[-29:], message]

    def _channel_assignment_for(self, channel_tag: str) -> int:
        return channel_assignment_for_tag(self.state.channel_assignments, channel_tag)
