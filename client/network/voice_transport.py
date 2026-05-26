from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
from time import monotonic, monotonic_ns
from collections.abc import Awaitable, Callable

from client.audio.opus_codec import OpusCodec
from client.models.audio import VoiceFrame
from shared.constants.network import DEFAULT_VOICE_PORT
from shared.protocol.messages import pack_voice_datagram, unpack_voice_datagram_with_role


ReceiveHandler = Callable[[VoiceFrame], Awaitable[None] | None]


class VoiceTransportClient:
    _KEEPALIVE_INTERVAL_SECONDS = 2.0

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_VOICE_PORT) -> None:
        self.host = host
        self.port = port
        self.session_id = 0
        self.channel_tag = "general"
        self.sender_role = "Soldier"
        self.codec = OpusCodec()
        self._socket: socket.socket | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._receive_handler: ReceiveHandler | None = None
        self._packet_number = 1
        self._registration_requested = False
        self._next_keepalive_at = 0.0
        self._last_received_packet_numbers: dict[int, int] = {}
        self._last_receive_times: dict[int, float] = {}
        self._send_lock = threading.Lock()
        self.last_send_error = ""

    def configure(self, host: str, session_id: int, channel_tag: str) -> None:
        changed = (host != self.host) or (session_id != self.session_id) or (channel_tag != self.channel_tag)
        self.host = host
        self.session_id = session_id
        self.channel_tag = channel_tag
        if changed and session_id > 0:
            self._registration_requested = True
            self._next_keepalive_at = 0.0
            self._last_received_packet_numbers.clear()
            self._last_receive_times.clear()

    def configure_role(self, sender_role: str) -> None:
        self.sender_role = sender_role.strip() or "Soldier"

    def set_receive_handler(self, handler: ReceiveHandler | None) -> None:
        self._receive_handler = handler

    def request_registration(self, *, send_now: bool = False) -> None:
        self._registration_requested = True
        self._next_keepalive_at = 0.0
        if send_now:
            self.send_keepalive_nowait()

    async def start(self) -> None:
        if self._socket is not None:
            return
        self.last_send_error = ""
        self._packet_number = 1
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
        self._socket.bind(("0.0.0.0", 0))
        self._receive_task = asyncio.create_task(self._receive_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        self._registration_requested = True
        self._next_keepalive_at = 0.0
        self._last_received_packet_numbers.clear()
        self._last_receive_times.clear()

    async def stop(self) -> None:
        for task_name in ("_receive_task", "_keepalive_task"):
            task = getattr(self, task_name)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                setattr(self, task_name, None)
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._registration_requested = False
        self._next_keepalive_at = 0.0
        self._last_received_packet_numbers.clear()
        self._last_receive_times.clear()
        self.last_send_error = ""

    async def send_pcm_frame(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        await asyncio.to_thread(self.send_pcm_frame_nowait, pcm_bytes)

    def send_pcm_frame_nowait(self, pcm_bytes: bytes) -> bool:
        if self._socket is None:
            self.last_send_error = "transport_not_started"
            return False
        if self.session_id == 0:
            self.last_send_error = "missing_session_id"
            return False
        if not pcm_bytes:
            self.last_send_error = "empty_pcm_frame"
            return False
        with self._send_lock:
            codec_name, payload = self.codec.encode(pcm_bytes)
            packet = pack_voice_datagram(
                self.session_id,
                self.channel_tag,
                payload,
                codec=codec_name,
                packet_number=self._next_packet_number(),
                sent_at_ms=self._capture_timestamp_ms(),
                sender_role=self.sender_role,
            )
            try:
                self._socket.sendto(packet, (self.host, self.port))
            except BlockingIOError:
                self.last_send_error = "socket_would_block"
                return False
            except OSError as exc:
                self.last_send_error = f"socket_send_failed:{exc}"
                return False
            self._registration_requested = False
            self._next_keepalive_at = monotonic() + self._KEEPALIVE_INTERVAL_SECONDS
            self.last_send_error = ""
            return True

    def send_keepalive_nowait(self) -> bool:
        if self._socket is None or self.session_id == 0:
            return False
        packet = self._keepalive_packet()
        with self._send_lock:
            try:
                self._socket.sendto(packet, (self.host, self.port))
            except (BlockingIOError, OSError):
                return False
            self._registration_requested = False
            self._next_keepalive_at = monotonic() + self._KEEPALIVE_INTERVAL_SECONDS
            return True

    async def _receive_loop(self) -> None:
        if self._socket is None:
            return
        loop = asyncio.get_running_loop()
        while True:
            packet, _ = await loop.sock_recvfrom(self._socket, 4096)
            session_id, channel_tag, codec_name, packet_number, sent_at_ms, payload, sender_role = unpack_voice_datagram_with_role(packet)
            now = monotonic()
            last_receive_at = self._last_receive_times.get(session_id, 0.0)
            last_packet_number = self._last_received_packet_numbers.get(session_id, 0)
            new_transmission = last_receive_at <= 0.0 or (now - last_receive_at) > 0.4
            missing_packets = 0
            if packet_number > 0 and last_packet_number > 0 and packet_number > (last_packet_number + 1):
                missing_packets = packet_number - last_packet_number - 1
            decoded_payload = self.codec.decode(
                codec_name,
                payload,
                missing_packets=missing_packets,
                new_transmission=new_transmission,
            )
            if packet_number > 0:
                self._last_received_packet_numbers[session_id] = packet_number
            self._last_receive_times[session_id] = now
            frame = VoiceFrame(
                session_id=session_id,
                channel_tag=channel_tag,
                codec=codec_name,
                packet_number=packet_number,
                sent_at_ms=sent_at_ms,
                sender_role=sender_role,
                pcm_bytes=decoded_payload,
                new_transmission=new_transmission,
                missing_packets=missing_packets,
            )
            if self._receive_handler is None:
                continue
            result = self._receive_handler(frame)
            if asyncio.iscoroutine(result):
                await result

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.5)
                if self._socket is None or self.session_id == 0:
                    continue
                now = monotonic()
                if not self._registration_requested and now < self._next_keepalive_at:
                    continue
                await self._send_keepalive()
                self._registration_requested = False
                self._next_keepalive_at = now + self._KEEPALIVE_INTERVAL_SECONDS
        except asyncio.CancelledError:
            return

    async def _send_keepalive(self) -> None:
        if self._socket is None or self.session_id == 0:
            return
        packet = self._keepalive_packet()
        loop = asyncio.get_running_loop()
        await loop.sock_sendto(self._socket, packet, (self.host, self.port))

    def _keepalive_packet(self) -> bytes:
        return pack_voice_datagram(
            self.session_id,
            self.channel_tag,
            b"",
            codec="pcm16",
            packet_number=0,
            sent_at_ms=self._capture_timestamp_ms(),
            sender_role=self.sender_role,
        )

    def _next_packet_number(self) -> int:
        packet_number = self._packet_number
        self._packet_number = (self._packet_number + 1) & 0xFFFFFFFF
        if self._packet_number == 0:
            self._packet_number = 1
        return packet_number

    def _capture_timestamp_ms(self) -> int:
        return (monotonic_ns() // 1_000_000) & 0xFFFFFFFF
