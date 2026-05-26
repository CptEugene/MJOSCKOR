import struct

from shared.protocol.messages import decode_control_message, encode_control_message, pack_voice_datagram, unpack_voice_datagram


def test_control_message_roundtrip() -> None:
    raw = encode_control_message("hello", {"callsign": "user"})
    decoded = decode_control_message(raw)
    assert decoded["type"] == "hello"
    assert decoded["payload"]["callsign"] == "user"


def test_voice_datagram_roundtrip() -> None:
    packet = pack_voice_datagram(7, "hq", b"abc", codec="opus", packet_number=42, sent_at_ms=123456)
    session_id, channel_tag, codec, packet_number, sent_at_ms, payload = unpack_voice_datagram(packet)
    assert session_id == 7
    assert channel_tag == "hq"
    assert codec == "opus"
    assert packet_number == 42
    assert sent_at_ms == 123456
    assert payload == b"abc"


def test_voice_datagram_v1_backward_compatibility() -> None:
    legacy_packet = struct.pack("!IBB", 9, 3, 1) + b"legacy"
    session_id, channel_tag, codec, packet_number, sent_at_ms, payload = unpack_voice_datagram(legacy_packet)
    assert session_id == 9
    assert channel_tag == "atc"
    assert codec == "pcm16"
    assert packet_number == 0
    assert sent_at_ms == 0
    assert payload == b"legacy"
