from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AudioDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    host_api_name: str = ""
    endpoint_id: str = ""


@dataclass(slots=True)
class VoiceFrame:
    session_id: int
    channel_tag: str
    codec: str
    pcm_bytes: bytes
    packet_number: int = 0
    sent_at_ms: int = 0
    sender_role: str = ""
    new_transmission: bool = False
    missing_packets: int = 0


@dataclass(slots=True)
class AudioSettings:
    microphone_device_index: int | None = None
    microphone_device_name: str = ""
    microphone_device_endpoint_id: str = ""
    speaker_device_index: int | None = None
    speaker_device_name: str = ""
    speaker_device_endpoint_id: str = ""
    microphone_volume_percent: int = 100
    speaker_volume_percent: int = 100
    channel_receive_volumes: list[int] = field(default_factory=lambda: [100, 100, 100, 100])
    channel_pan_modes: list[str] = field(default_factory=lambda: ["both", "both", "both", "both"])


@dataclass(slots=True)
class AudioRuntimeState:
    input_devices: list[AudioDeviceInfo] = field(default_factory=list)
    output_devices: list[AudioDeviceInfo] = field(default_factory=list)
    microphone_level: float = 0.0
    transmitting: bool = False
    rx_packets_late_dropped: int = 0
    rx_packets_overflow_dropped: int = 0
    rx_packets_skipped: int = 0
    effect_chunks_dropped: int = 0
    tx_preroll_frames_sent: int = 0
    tx_release_frames_sent: int = 0
    last_error: str = ""
