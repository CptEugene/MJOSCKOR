import asyncio
import socket

from client.network.voice_transport import VoiceTransportClient
from shared.protocol.messages import unpack_voice_datagram


async def _receive_registration_packet() -> tuple[int, str, bytes]:
    loop = asyncio.get_running_loop()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setblocking(False)
    server_socket.bind(("127.0.0.1", 0))
    host, port = server_socket.getsockname()
    transport = VoiceTransportClient(host=host, port=port)
    try:
        transport.configure(host=host, session_id=42, channel_tag="general")
        await transport.start()
        packet, _addr = await asyncio.wait_for(loop.sock_recvfrom(server_socket, 4096), timeout=1.0)
        session_id, channel_tag, _codec, _packet_number, _sent_at_ms, payload = unpack_voice_datagram(packet)
        return session_id, channel_tag, payload
    finally:
        await transport.stop()
        server_socket.close()


def test_voice_transport_sends_udp_registration_keepalive_on_start() -> None:
    session_id, channel_tag, payload = asyncio.run(_receive_registration_packet())

    assert session_id == 42
    assert channel_tag == "general"
    assert payload == b""


def test_voice_transport_uses_short_keepalive_interval() -> None:
    assert VoiceTransportClient._KEEPALIVE_INTERVAL_SECONDS == 2.0
