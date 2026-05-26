from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass
from typing import Any


CONTROL_PROTOCOL = "jsonl-v1"
VOICE_PACKET_MAGIC = b"MV"
VOICE_PACKET_VERSION = 2
VOICE_HEADER_STRUCT_V1 = struct.Struct("!IBB")
VOICE_HEADER_STRUCT_V2 = struct.Struct("!2sBIBBII")
VOICE_ROLE_PAYLOAD_MAGIC = b"MR"
CHANNEL_TAG_TO_CODE = {"squad": 1, "hq": 2, "atc": 3, "general": 4}
CHANNEL_CODE_TO_TAG = {value: key for key, value in CHANNEL_TAG_TO_CODE.items()}
VOICE_CODEC_TO_CODE = {"pcm16": 1, "opus": 2}
VOICE_CODE_TO_CODEC = {value: key for key, value in VOICE_CODEC_TO_CODE.items()}
ROLE_TO_CODE = {"commander": 1, "officer": 2, "pilot": 3, "soldier": 4}
CODE_TO_ROLE = {value: key.title() for key, value in ROLE_TO_CODE.items()}


@dataclass(slots=True)
class HelloMessage:
    callsign: str
    server_password: str


@dataclass(slots=True)
class HelloAckMessage:
    session_id: int


def encode_control_message(message_type: str, payload: dict[str, Any]) -> bytes:
    envelope = {"type": message_type, "payload": payload}
    return (json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8")


def encode_dataclass_message(message_type: str, payload: Any) -> bytes:
    return encode_control_message(message_type, asdict(payload))


def decode_control_message(line: bytes) -> dict[str, Any]:
    return json.loads(line.decode("utf-8"))


def pack_voice_datagram(
    session_id: int,
    channel_tag: str,
    payload: bytes,
    codec: str = "pcm16",
    packet_number: int = 0,
    sent_at_ms: int = 0,
    sender_role: str = "",
) -> bytes:
    channel_code = CHANNEL_TAG_TO_CODE.get(channel_tag.lower(), 4)
    codec_code = VOICE_CODEC_TO_CODE.get(codec.lower(), 1)
    role_code = ROLE_TO_CODE.get(sender_role.strip().lower(), 0)
    encoded_payload = (VOICE_ROLE_PAYLOAD_MAGIC + bytes([role_code]) + payload) if role_code else payload
    header = VOICE_HEADER_STRUCT_V2.pack(
        VOICE_PACKET_MAGIC,
        VOICE_PACKET_VERSION,
        session_id,
        channel_code,
        codec_code,
        packet_number & 0xFFFFFFFF,
        sent_at_ms & 0xFFFFFFFF,
    )
    return header + encoded_payload


def unpack_voice_datagram(packet: bytes) -> tuple[int, str, str, int, int, bytes]:
    session_id, channel_tag, codec, packet_number, sent_at_ms, payload, _sender_role = unpack_voice_datagram_with_role(packet)
    return session_id, channel_tag, codec, packet_number, sent_at_ms, payload


def unpack_voice_datagram_with_role(packet: bytes) -> tuple[int, str, str, int, int, bytes, str]:
    if len(packet) >= VOICE_HEADER_STRUCT_V2.size and packet.startswith(VOICE_PACKET_MAGIC):
        magic, version, session_id, channel_code, codec_code, packet_number, sent_at_ms = (
            VOICE_HEADER_STRUCT_V2.unpack_from(packet, 0)
        )
        if magic != VOICE_PACKET_MAGIC or version != VOICE_PACKET_VERSION:
            raise ValueError("unsupported voice packet version")
        payload, sender_role = _decode_role_payload(packet[VOICE_HEADER_STRUCT_V2.size :])
        return (
            session_id,
            CHANNEL_CODE_TO_TAG.get(channel_code, "general"),
            VOICE_CODE_TO_CODEC.get(codec_code, "pcm16"),
            packet_number,
            sent_at_ms,
            payload,
            sender_role,
        )
    if len(packet) < VOICE_HEADER_STRUCT_V1.size:
        raise ValueError("voice packet too small")
    session_id, channel_code, codec_code = VOICE_HEADER_STRUCT_V1.unpack_from(packet, 0)
    payload, sender_role = _decode_role_payload(packet[VOICE_HEADER_STRUCT_V1.size :])
    return (
        session_id,
        CHANNEL_CODE_TO_TAG.get(channel_code, "general"),
        VOICE_CODE_TO_CODEC.get(codec_code, "pcm16"),
        0,
        0,
        payload,
        sender_role,
    )


def _decode_role_payload(payload: bytes) -> tuple[bytes, str]:
    if len(payload) >= 3 and payload.startswith(VOICE_ROLE_PAYLOAD_MAGIC):
        return payload[3:], CODE_TO_ROLE.get(payload[2], "")
    return payload, ""
