import asyncio
import socket

import pytest

from client.network.control_client import ControlClient
from server.app.server_core import MaydayServerCore
from shared.constants.app_version import APP_VERSION
from shared.constants.security import ADMIN_PASSWORD
from shared.constants.paths import runtime_paths
from shared.protocol.messages import decode_control_message, encode_control_message, pack_voice_datagram, unpack_voice_datagram


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def _run_roundtrip() -> tuple[bool, str, str]:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    client = ControlClient()
    try:
        ok, reason = await client.connect_test("user", "127.0.0.1", server.server_password, port=server.control_port)
        return ok, reason, server.tree_text
    finally:
        client.close()
        await server.stop()


def test_control_roundtrip() -> None:
    ok, reason, tree_text = asyncio.run(_run_roundtrip())
    assert ok is True
    assert reason == "connected"
    assert '"fleets"' in tree_text


async def _run_probe_roundtrip() -> list[str]:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader = writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        writer.write(
            encode_control_message(
                "hello",
                {
                    "callsign": "ProbeUser",
                    "server_password": server.server_password,
                    "probe": True,
                    "client_version": APP_VERSION,
                },
            )
        )
        await writer.drain()
        hello_ack = await _read_until_type(reader, "hello_ack")
        assert int(hello_ack["payload"]["session_id"]) > 0
        messages: list[str] = []
        while True:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=0.15)
            except TimeoutError:
                break
            if not raw:
                break
            messages.append(str(decode_control_message(raw).get("type", "")))
        return messages
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await server.stop()


def test_probe_hello_only_receives_hello_ack() -> None:
    extra_messages = asyncio.run(_run_probe_roundtrip())
    assert extra_messages == []


async def _read_until_type(reader: asyncio.StreamReader, expected_type: str) -> dict:
    while True:
        raw = await asyncio.wait_for(reader.readline(), timeout=3.0)
        if not raw:
            raise AssertionError("connection closed before expected message arrived")
        message = decode_control_message(raw)
        if message.get("type") == expected_type:
            return message


async def _wait_for_presence_count(reader: asyncio.StreamReader, expected_count: int) -> dict:
    while True:
        message = await _read_until_type(reader, "presence_snapshot")
        entries = list(message.get("payload", {}).get("entries", []))
        if len(entries) >= expected_count:
            return message


async def _wait_for_kneeboard_text(reader: asyncio.StreamReader, expected_text: str) -> dict:
    while True:
        message = await _read_until_type(reader, "kneeboard_snapshot")
        if str(message.get("payload", {}).get("text", "")) == expected_text:
            return message


async def _hello(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, callsign: str, server_password: str) -> int:
    writer.write(
        encode_control_message(
            "hello",
            {
                "callsign": callsign,
                "server_password": server_password,
                "client_version": APP_VERSION,
            },
        )
    )
    await writer.drain()
    hello_ack = await _read_until_type(reader, "hello_ack")
    return int(hello_ack["payload"]["session_id"])


async def _hello_sync_only(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, callsign: str, server_password: str) -> int:
    writer.write(
        encode_control_message(
            "hello",
            {
                "callsign": callsign,
                "server_password": server_password,
                "client_version": APP_VERSION,
                "sync_only": True,
            },
        )
    )
    await writer.drain()
    hello_ack = await _read_until_type(reader, "hello_ack")
    return int(hello_ack["payload"]["session_id"])


async def _run_outdated_client_rejected() -> str:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader = writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        writer.write(
            encode_control_message(
                "hello",
                {
                    "callsign": "OldClient",
                    "server_password": server.server_password,
                    "client_version": "0.0.1",
                },
            )
        )
        await writer.drain()
        message = await _read_until_type(reader, "error")
        return str(message.get("payload", {}).get("reason", ""))
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await server.stop()


def test_outdated_client_is_rejected() -> None:
    reason = asyncio.run(_run_outdated_client_rejected())
    assert reason == "client_update_required"


async def _run_configured_minimum_client_version_rejected() -> str:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    server.minimum_client_version = "9.9.9"
    await server.start()
    client = ControlClient()
    try:
        ok, reason = await client.connect_test(
            "ConfiguredOldClient",
            "127.0.0.1",
            server.server_password,
            port=server.control_port,
        )
        assert ok is False
        return reason
    finally:
        client.close()
        await server.stop()


def test_configured_minimum_client_version_is_enforced() -> None:
    reason = asyncio.run(_run_configured_minimum_client_version_rejected())
    assert reason == "client_update_required"


async def _set_all_channels_to_one(writer: asyncio.StreamWriter) -> None:
    writer.write(encode_control_message("channel_config", {"channel_assignments": [1, 1, 1, 1]}))
    await writer.drain()


async def _run_chat_roundtrip() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        session_a = await _hello(reader_a, writer_a, "Alpha", server.server_password)
        _ = await _hello(reader_b, writer_b, "Bravo", server.server_password)
        writer_a.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-a",
                    "node_id": "node-a",
                    "role": "Commander",
                },
            )
        )
        await writer_a.drain()
        writer_b.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-b",
                    "wing_id": "wing-b",
                    "squad_id": "squad-b",
                    "slot_id": "slot-b",
                    "node_id": "node-b",
                    "role": "Pilot",
                },
            )
        )
        await writer_b.drain()
        await _wait_for_presence_count(reader_a, 2)
        await _wait_for_presence_count(reader_b, 2)
        writer_a.write(encode_control_message("chat_message", {"text": "Hello fleet"}))
        await writer_a.drain()
        message_a = await _read_until_type(reader_a, "chat_message")
        message_b = await _read_until_type(reader_b, "chat_message")
        assert message_a["payload"] == message_b["payload"]
        assert int(message_b["payload"]["session_id"]) == session_a
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_chat_roundtrip() -> None:
    payload = asyncio.run(_run_chat_roundtrip())
    assert payload["callsign"] == "Alpha"
    assert payload["role"] == "Commander"
    assert payload["text"] == "Hello fleet"


async def _run_chat_allows_connected_client_without_slot() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader = writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        session_id = await _hello(reader, writer, "Unslotted", server.server_password)
        writer.write(encode_control_message("chat_message", {"text": "connected chat"}))
        await writer.drain()
        message = await _read_until_type(reader, "chat_message")
        payload = dict(message["payload"])
        payload["expected_session_id"] = session_id
        return payload
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await server.stop()


def test_chat_allows_connected_client_without_slot() -> None:
    payload = asyncio.run(_run_chat_allows_connected_client_without_slot())
    assert int(payload["session_id"]) == int(payload["expected_session_id"])
    assert payload["callsign"] == "Unslotted"
    assert payload["text"] == "connected chat"


async def _run_chat_log_split_roundtrip(tmp_path) -> tuple[str, str]:
    root_dir = tmp_path / "root"
    data_dir = tmp_path / "runtime" / "server" / "data"
    logs_dir = tmp_path / "runtime" / "server" / "logs"
    server = MaydayServerCore(root_dir, data_dir, logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader = writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader, writer, "Logger", server.server_password)
        writer.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-log",
                    "wing_id": "wing-log",
                    "squad_id": "squad-log",
                    "slot_id": "slot-log",
                    "node_id": "node-log",
                    "role": "Officer",
                },
            )
        )
        await writer.drain()
        writer.write(encode_control_message("chat_message", {"text": "split logs"}))
        await writer.drain()
        _ = await _read_until_type(reader, "chat_message")
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await server.stop()
    server_log = (logs_dir / "server.log").read_text(encoding="utf-8")
    chat_log = (logs_dir / "chat.log").read_text(encoding="utf-8")
    return server_log, chat_log


def test_chat_logs_are_separate(tmp_path) -> None:
    server_log, chat_log = asyncio.run(_run_chat_log_split_roundtrip(tmp_path))
    assert "split logs" not in server_log
    assert "CHAT from" not in server_log
    assert "Logger (127.0.0.1): split logs" in chat_log


async def _run_kneeboard_roundtrip(tmp_path) -> tuple[str, str]:
    root_dir = tmp_path / "root"
    data_dir = tmp_path / "runtime" / "server" / "data"
    logs_dir = tmp_path / "runtime" / "server" / "logs"
    server = MaydayServerCore(root_dir, data_dir, logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "Commander", server.server_password)
        _ = await _hello(reader_b, writer_b, "Pilot", server.server_password)
        text = "Briefing line 1\nBriefing line 2"
        writer_a.write(
            encode_control_message(
                "kneeboard_update",
                {
                    "text": text,
                    "admin_password": ADMIN_PASSWORD,
                },
            )
        )
        await writer_a.drain()
        message_a = await _wait_for_kneeboard_text(reader_a, text)
        message_b = await _wait_for_kneeboard_text(reader_b, text)
        assert message_a["payload"] == message_b["payload"]
        return message_b["payload"]["text"], (data_dir / "kneeboard.txt").read_text(encoding="utf-8")
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_kneeboard_update_broadcasts_and_persists(tmp_path) -> None:
    broadcast_text, persisted_text = asyncio.run(_run_kneeboard_roundtrip(tmp_path))
    assert broadcast_text == "Briefing line 1\nBriefing line 2"
    assert persisted_text == broadcast_text


async def _run_soundtrack_roundtrip() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "DJ", server.server_password)
        _ = await _hello(reader_b, writer_b, "Listener", server.server_password)
        writer_a.write(
            encode_control_message(
                "soundtrack_control",
                {
                    "action": "play",
                    "track_id": "briefing_theme.mp3",
                    "admin_password": ADMIN_PASSWORD,
                    "volume_percent": 85,
                    "fade_ms": 1500,
                },
            )
        )
        await writer_a.drain()
        message_a = await _read_until_type(reader_a, "soundtrack_control")
        message_b = await _read_until_type(reader_b, "soundtrack_control")
        assert message_a["payload"] == message_b["payload"]
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_soundtrack_control_roundtrip() -> None:
    payload = asyncio.run(_run_soundtrack_roundtrip())
    assert payload["action"] == "play"
    assert payload["track_id"] == "briefing_theme.mp3"
    assert payload["volume_percent"] == 85
    assert payload["fade_ms"] == 1500
    assert payload["start_at_ms"] > 0
    assert payload["start_delay_ms"] == 2000


async def _run_soundtrack_control_reaches_sync_only_listener() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "DJ", server.server_password)
        _ = await _hello_sync_only(reader_b, writer_b, "MediaListener", server.server_password)
        writer_a.write(
            encode_control_message(
                "soundtrack_control",
                {
                    "action": "play",
                    "track_id": "briefing_theme.mp3",
                    "admin_password": ADMIN_PASSWORD,
                    "volume_percent": 85,
                    "fade_ms": 1500,
                },
            )
        )
        await writer_a.drain()
        message_b = await _read_until_type(reader_b, "soundtrack_control")
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_soundtrack_control_reaches_sync_only_listener() -> None:
    payload = asyncio.run(_run_soundtrack_control_reaches_sync_only_listener())
    assert payload["action"] == "play"
    assert payload["track_id"] == "briefing_theme.mp3"


async def _run_soundtrack_stop_roundtrip() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    last_error: OSError | None = None
    for _ in range(5):
        server.control_port = _free_port()
        server.voice_port = _free_port()
        try:
            await server.start()
            break
        except OSError as exc:
            last_error = exc
    else:
        raise last_error or RuntimeError("server failed to start")
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "DJ", server.server_password)
        _ = await _hello(reader_b, writer_b, "Listener", server.server_password)
        writer_a.write(
            encode_control_message(
                "soundtrack_control",
                {
                    "action": "stop",
                    "admin_password": ADMIN_PASSWORD,
                    "fade_ms": 900,
                },
            )
        )
        await writer_a.drain()
        message_a = await _read_until_type(reader_a, "soundtrack_control")
        message_b = await _read_until_type(reader_b, "soundtrack_control")
        assert message_a["payload"] == message_b["payload"]
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_soundtrack_stop_roundtrip() -> None:
    payload = asyncio.run(_run_soundtrack_stop_roundtrip())
    assert payload["action"] == "stop"
    assert payload["fade_ms"] == 900


async def _run_mission_overlay_roundtrip() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "Commander", server.server_password)
        _ = await _hello(reader_b, writer_b, "Wingman", server.server_password)
        writer_a.write(
            encode_control_message(
                "mission_overlay",
                {
                    "text": "Primary objective updated",
                    "admin_password": ADMIN_PASSWORD,
                    "duration_ms": 4200,
                    "fade_ms": 500,
                },
            )
        )
        await writer_a.drain()
        message_a = await _read_until_type(reader_a, "mission_overlay")
        message_b = await _read_until_type(reader_b, "mission_overlay")
        assert message_a["payload"] == message_b["payload"]
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_mission_overlay_roundtrip() -> None:
    payload = asyncio.run(_run_mission_overlay_roundtrip())
    assert payload["text"] == "Primary objective updated"
    assert payload["duration_ms"] == 4200
    assert payload["fade_ms"] == 500
    assert payload["color"] == "white"
    assert payload["font_scale"] == 1.0


async def _run_video_overlay_roundtrip() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "Commander", server.server_password)
        _ = await _hello(reader_b, writer_b, "Wingman", server.server_password)
        writer_a.write(
            encode_control_message(
                "video_overlay",
                {
                    "action": "play",
                    "video_id": "mission_intro.mp4",
                    "admin_password": ADMIN_PASSWORD,
                    "volume_percent": 92,
                },
            )
        )
        await writer_a.drain()
        message_a = await _read_until_type(reader_a, "video_overlay")
        message_b = await _read_until_type(reader_b, "video_overlay")
        assert message_a["payload"] == message_b["payload"]
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_video_overlay_roundtrip() -> None:
    payload = asyncio.run(_run_video_overlay_roundtrip())
    assert payload["action"] == "play"
    assert payload["video_id"] == "mission_intro.mp4"
    assert payload["volume_percent"] == 92
    assert int(payload["start_at_ms"]) > 0
    assert payload["start_delay_ms"] == 2000


async def _run_video_overlay_reaches_sync_only_listener() -> dict:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader_a = reader_b = None
    writer_a = writer_b = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader_a, writer_a, "Commander", server.server_password)
        _ = await _hello_sync_only(reader_b, writer_b, "VideoListener", server.server_password)
        writer_a.write(
            encode_control_message(
                "video_overlay",
                {
                    "action": "play",
                    "video_id": "mission_intro.mp4",
                    "admin_password": ADMIN_PASSWORD,
                    "volume_percent": 92,
                },
            )
        )
        await writer_a.drain()
        message_b = await _read_until_type(reader_b, "video_overlay")
        return message_b["payload"]
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_video_overlay_reaches_sync_only_listener() -> None:
    payload = asyncio.run(_run_video_overlay_reaches_sync_only_listener())
    assert payload["action"] == "play"
    assert payload["video_id"] == "mission_intro.mp4"


async def _run_voice_registration_roundtrip() -> bytes:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    last_error: OSError | None = None
    for _ in range(5):
        server.control_port = _free_port()
        server.voice_port = _free_port()
        try:
            await server.start()
            break
        except OSError as exc:
            last_error = exc
    else:
        raise last_error or RuntimeError("server failed to start")
    reader_a = reader_b = None
    writer_a = writer_b = None
    talker_socket = listener_socket = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        talker_session = await _hello(reader_a, writer_a, "Talker", server.server_password)
        listener_session = await _hello(reader_b, writer_b, "Listener", server.server_password)
        writer_a.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-talker",
                    "node_id": "node-talker",
                    "role": "Commander",
                },
            )
        )
        await writer_a.drain()
        writer_b.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-listener",
                    "node_id": "node-listener",
                    "role": "Pilot",
                },
            )
        )
        await writer_b.drain()
        await _set_all_channels_to_one(writer_b)
        writer_a.write(
            encode_control_message(
                "ptt_state",
                {"pressed": True, "channel_tag": "general", "channel_number": 1},
            )
        )
        await writer_a.drain()

        loop = asyncio.get_running_loop()
        talker_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        talker_socket.setblocking(False)
        talker_socket.bind(("127.0.0.1", 0))

        listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener_socket.setblocking(False)
        listener_socket.bind(("127.0.0.1", 0))

        registration_packet = pack_voice_datagram(listener_session, "general", b"")
        await loop.sock_sendto(listener_socket, registration_packet, ("127.0.0.1", server.voice_port))

        voice_packet = pack_voice_datagram(talker_session, "general", b"voice-payload", codec="pcm16")
        await loop.sock_sendto(talker_socket, voice_packet, ("127.0.0.1", server.voice_port))
        packet, _ = await asyncio.wait_for(loop.sock_recvfrom(listener_socket, 4096), timeout=2.0)
        return packet
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        for udp_socket in (talker_socket, listener_socket):
            if udp_socket is not None:
                udp_socket.close()
        await server.stop()


def test_voice_registration_allows_receiving_before_transmit() -> None:
    packet = asyncio.run(_run_voice_registration_roundtrip())
    session_id, channel_tag, codec_name, _packet_number, _sent_at_ms, payload = unpack_voice_datagram(packet)
    assert session_id > 0
    assert channel_tag == "general"
    assert codec_name == "pcm16"
    assert payload == b"voice-payload"


async def _run_soldier_atc_roundtrip() -> bytes:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    last_error: OSError | None = None
    for _ in range(5):
        server.control_port = _free_port()
        server.voice_port = _free_port()
        try:
            await server.start()
            break
        except OSError as exc:
            last_error = exc
    else:
        raise last_error or RuntimeError("server failed to start")
    reader_a = reader_b = None
    writer_a = writer_b = None
    talker_socket = listener_socket = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        talker_session = await _hello(reader_a, writer_a, "CommanderTalker", server.server_password)
        listener_session = await _hello(reader_b, writer_b, "SoldierListener", server.server_password)

        writer_a.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-commander",
                    "node_id": "node-commander",
                    "role": "Commander",
                },
            )
        )
        await writer_a.drain()
        writer_b.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-soldier",
                    "node_id": "node-soldier",
                    "role": "Soldier",
                },
            )
        )
        await writer_b.drain()
        await _set_all_channels_to_one(writer_b)

        writer_a.write(
            encode_control_message(
                "ptt_state",
                {"pressed": True, "channel_tag": "atc", "channel_number": 1},
            )
        )
        await writer_a.drain()

        loop = asyncio.get_running_loop()
        talker_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        talker_socket.setblocking(False)
        talker_socket.bind(("127.0.0.1", 0))

        listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener_socket.setblocking(False)
        listener_socket.bind(("127.0.0.1", 0))

        registration_packet = pack_voice_datagram(listener_session, "atc", b"")
        await loop.sock_sendto(listener_socket, registration_packet, ("127.0.0.1", server.voice_port))

        voice_packet = pack_voice_datagram(talker_session, "atc", b"soldier-atc", codec="pcm16")
        await loop.sock_sendto(talker_socket, voice_packet, ("127.0.0.1", server.voice_port))
        packet, _ = await asyncio.wait_for(loop.sock_recvfrom(listener_socket, 4096), timeout=2.0)
        return packet
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        for udp_socket in (talker_socket, listener_socket):
            if udp_socket is not None:
                udp_socket.close()
        await server.stop()


def test_soldier_listener_receives_atc_channel_voice() -> None:
    packet = asyncio.run(_run_soldier_atc_roundtrip())
    session_id, channel_tag, codec_name, _packet_number, _sent_at_ms, payload = unpack_voice_datagram(packet)
    assert session_id > 0
    assert channel_tag == "atc"
    assert codec_name == "pcm16"
    assert payload == b"soldier-atc"


async def _run_soldier_general_roundtrip() -> bytes:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    last_error: OSError | None = None
    for _ in range(5):
        server.control_port = _free_port()
        server.voice_port = _free_port()
        try:
            await server.start()
            break
        except OSError as exc:
            last_error = exc
    else:
        raise last_error or RuntimeError("server failed to start")
    reader_a = reader_b = None
    writer_a = writer_b = None
    talker_socket = listener_socket = None
    try:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", server.control_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", server.control_port)
        talker_session = await _hello(reader_a, writer_a, "CommanderTalker", server.server_password)
        listener_session = await _hello(reader_b, writer_b, "SoldierListener", server.server_password)

        writer_a.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-commander",
                    "node_id": "node-commander",
                    "role": "Commander",
                },
            )
        )
        await writer_a.drain()
        writer_b.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-soldier",
                    "node_id": "node-soldier",
                    "role": "Soldier",
                },
            )
        )
        await writer_b.drain()
        await _set_all_channels_to_one(writer_b)

        writer_a.write(
            encode_control_message(
                "ptt_state",
                {"pressed": True, "channel_tag": "general", "channel_number": 1},
            )
        )
        await writer_a.drain()

        loop = asyncio.get_running_loop()
        talker_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        talker_socket.setblocking(False)
        talker_socket.bind(("127.0.0.1", 0))

        listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener_socket.setblocking(False)
        listener_socket.bind(("127.0.0.1", 0))

        registration_packet = pack_voice_datagram(listener_session, "general", b"")
        await loop.sock_sendto(listener_socket, registration_packet, ("127.0.0.1", server.voice_port))

        voice_packet = pack_voice_datagram(talker_session, "general", b"soldier-general", codec="pcm16")
        await loop.sock_sendto(talker_socket, voice_packet, ("127.0.0.1", server.voice_port))
        packet, _ = await asyncio.wait_for(loop.sock_recvfrom(listener_socket, 4096), timeout=2.0)
        return packet
    finally:
        for writer in (writer_a, writer_b):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        for udp_socket in (talker_socket, listener_socket):
            if udp_socket is not None:
                udp_socket.close()
        await server.stop()


def test_soldier_listener_receives_general_channel_voice() -> None:
    packet = asyncio.run(_run_soldier_general_roundtrip())
    session_id, channel_tag, codec_name, _packet_number, _sent_at_ms, payload = unpack_voice_datagram(packet)
    assert session_id > 0
    assert channel_tag == "general"
    assert codec_name == "pcm16"
    assert payload == b"soldier-general"


async def _run_unauthenticated_broadcast_guard() -> None:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    raw_reader = raw_writer = auth_reader = auth_writer = None
    try:
        raw_reader, raw_writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        auth_reader, auth_writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(auth_reader, auth_writer, "Alpha", server.server_password)
        auth_writer.write(
            encode_control_message(
                "join_node",
                {
                    "fleet_id": "fleet-a",
                    "wing_id": "wing-a",
                    "squad_id": "squad-a",
                    "slot_id": "slot-a",
                    "node_id": "node-a",
                    "role": "Commander",
                },
            )
        )
        await auth_writer.drain()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(raw_reader.readline(), timeout=0.25)
    finally:
        for writer in (raw_writer, auth_writer):
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        await server.stop()


def test_unauthenticated_connections_do_not_receive_broadcasts() -> None:
    asyncio.run(_run_unauthenticated_broadcast_guard())


async def _run_admin_command_guard() -> tuple[str, str, str]:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader = writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader, writer, "AdminProbe", server.server_password)

        writer.write(encode_control_message("tree_update", {"tree_text": "{\"fleets\": []}"}))
        await writer.drain()
        tree_error = await _read_until_type(reader, "error")

        writer.write(
            encode_control_message(
                "soundtrack_control",
                {"action": "play", "track_id": "briefing_theme.mp3", "volume_percent": 100, "fade_ms": 0},
            )
        )
        await writer.drain()
        soundtrack_error = await _read_until_type(reader, "error")

        writer.write(
            encode_control_message(
                "mission_overlay",
                {"text": "Unauthorized overlay"},
            )
        )
        await writer.drain()
        mission_error = await _read_until_type(reader, "error")

        return (
            str(tree_error["payload"]["reason"]),
            str(soundtrack_error["payload"]["reason"]),
            str(mission_error["payload"]["reason"]),
        )
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await server.stop()


def test_admin_commands_require_server_side_auth() -> None:
    tree_reason, soundtrack_reason, mission_reason = asyncio.run(_run_admin_command_guard())
    assert tree_reason == "admin_auth_required"
    assert soundtrack_reason == "admin_auth_required"
    assert mission_reason == "admin_auth_required"


async def _run_admin_command_success() -> str:
    paths = runtime_paths()
    server = MaydayServerCore(paths.root_dir, paths.server_data_dir, paths.server_logs_dir)
    server.control_port = _free_port()
    server.voice_port = _free_port()
    await server.start()
    reader = writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.control_port)
        _ = await _hello(reader, writer, "Admin", server.server_password)
        _ = await _read_until_type(reader, "tree_snapshot")
        writer.write(
            encode_control_message(
                "tree_update",
                {"tree_text": "{\"fleets\": []}", "admin_password": ADMIN_PASSWORD},
            )
        )
        await writer.drain()
        tree_snapshot = await _read_until_type(reader, "tree_snapshot")
        return str(tree_snapshot["payload"]["tree_text"])
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        await server.stop()


def test_admin_commands_succeed_with_admin_password() -> None:
    tree_text = asyncio.run(_run_admin_command_success())
    assert '"fleets": []' in tree_text
