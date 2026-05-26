from __future__ import annotations

import audioop
from functools import lru_cache
from pathlib import Path
import wave

from shared.constants.paths import runtime_paths

SAMPLE_RATE = 48_000


def _channel_prefix(channel_tag: str) -> str:
    return {
        "squad": "CH1",
        "hq": "CH2",
        "atc": "CH23",
        "general": "CH4",
    }.get(channel_tag.strip().lower(), "CH4")


def _read_wav_pcm(path: Path) -> bytes:
    if not path.exists():
        return b""
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        pcm = wav_file.readframes(frame_count)

    if sample_width != 2:
        return b""
    if channels > 1:
        pcm = audioop.tomono(pcm, sample_width, 0.5, 0.5)
    if sample_rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, sample_width, 1, sample_rate, SAMPLE_RATE, None)
    return pcm


@lru_cache(maxsize=16)
def _load_effect(prefix: str, suffix: str) -> bytes:
    sound_dir = runtime_paths().sound_dir
    return _read_wav_pcm(sound_dir / f"{prefix}_{suffix}.wav")


def _radio_tone(channel_tag: str, suffix: str) -> bytes:
    if channel_tag.strip().lower() != "general":
        return b""
    return _load_effect(_channel_prefix(channel_tag), suffix)


@lru_cache(maxsize=16)
def tx_start_tone(channel_tag: str) -> bytes:
    return _radio_tone(channel_tag, "start")


@lru_cache(maxsize=16)
def tx_end_tone(channel_tag: str) -> bytes:
    return _radio_tone(channel_tag, "end")


@lru_cache(maxsize=16)
def rx_start_tone(channel_tag: str) -> bytes:
    del channel_tag
    return _read_wav_pcm(runtime_paths().sound_dir / "comms.wav")


@lru_cache(maxsize=16)
def rx_end_tone(channel_tag: str) -> bytes:
    del channel_tag
    return b""
