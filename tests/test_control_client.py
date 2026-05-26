import asyncio

from client.network.control_client import ControlClient
from shared.protocol.messages import encode_control_message


async def _run_probe_server(port: int) -> None:
    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.readline()
        writer.write(encode_control_message("presence_snapshot", {"entries": []}))
        writer.write(encode_control_message("hello_ack", {"session_id": 99}))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handle, "127.0.0.1", port)
    async with server:
        await server.serve_forever()


def test_connect_test_ignores_unsolicited_messages_before_hello_ack(free_tcp_port: int) -> None:
    async def _run() -> tuple[bool, str]:
        server_task = asyncio.create_task(_run_probe_server(free_tcp_port))
        await asyncio.sleep(0.05)
        client = ControlClient()
        try:
            return await client.connect_test("Probe", "127.0.0.1", "", port=free_tcp_port)
        finally:
            client.close()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    ok, reason = asyncio.run(_run())
    assert ok is True
    assert reason == "connected"


def test_disconnect_clears_tree_presence_and_chat_state() -> None:
    client = ControlClient()
    try:
        client.state.connected = True
        client.state.session_id = 7
        client.state.selected_role = "Commander"
        client.state.selected_node_id = "node-a"
        client.state.tree_text = "stale-tree"
        client.state.kneeboard_text = "stale-kneeboard"
        client.state.presence_entries = ["stale"]  # type: ignore[list-item]
        client.state.chat_entries = ["stale"]  # type: ignore[list-item]
        client.state.admin_password = "5573"

        future = asyncio.run_coroutine_threadsafe(client._disconnect(), client._loop)
        future.result(timeout=3)

        assert client.state.connected is False
        assert client.state.session_id == 0
        assert client.state.selected_role == ""
        assert client.state.selected_node_id == ""
        assert client.state.tree_text == ""
        assert client.state.kneeboard_text == ""
        assert client.state.presence_entries == []
        assert client.state.chat_entries == []
        assert client.state.admin_password == ""
    finally:
        client.close()


def test_join_slot_does_not_preemptively_change_selected_role() -> None:
    client = ControlClient()
    try:
        client.state.selected_role = "Soldier"

        client.join_slot(
            fleet_id="fleet-a",
            wing_id="wing-a",
            squad_id="squad-a",
            slot_id="slot-a",
            node_id="node-a",
            role="Commander",
        )

        assert client.state.selected_role == "Soldier"
    finally:
        client.close()
