from __future__ import annotations

import audioop
import ctypes
import os
from pathlib import Path

from shared.constants.paths import runtime_paths


OPUS_ENCODE_FRAME_SIZE = 960
OPUS_DECODE_FRAME_SIZE = 1920
OPUS_ENCODE_SAMPLE_RATE = 48_000
OPUS_DECODE_SAMPLE_RATE = 48_000
OPUS_CHANNELS = 1
OPUS_MAX_PACKET_BYTES = 4000
OPUS_APPLICATION_VOIP = 2048
OPUS_SET_INBAND_FEC = 4012
OPUS_RESET_STATE = 4028


def _candidate_dll_paths() -> list[Path]:
    paths = runtime_paths()
    candidates = [
        paths.bin_dir / "opus.dll",
        paths.assets_dir / "bin" / "opus.dll",
        Path(__file__).resolve().parents[3] / "_refs" / "DCS-SimpleRadioStandalone" / "SharedAudio" / "opus.dll",
    ]
    return [candidate for candidate in candidates if candidate.exists()]


def _prepare_opus_environment() -> None:
    for dll_path in _candidate_dll_paths():
        parent = str(dll_path.parent)
        try:
            os.add_dll_directory(parent)
        except (AttributeError, FileNotFoundError):
            pass
        current_path = os.environ.get("PATH", "")
        if parent.lower() not in current_path.lower():
            os.environ["PATH"] = parent + os.pathsep + current_path


class _NativeOpusLibrary:
    _library: ctypes.WinDLL | None = None
    _library_error: str | None = None

    @classmethod
    def load(cls):
        if cls._library is not None:
            return cls._library
        if cls._library_error is not None:
            return None
        try:
            _prepare_opus_environment()
            library = ctypes.WinDLL("opus.dll")
            library.opus_encoder_create.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            library.opus_encoder_create.restype = ctypes.c_void_p
            library.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
            library.opus_encoder_destroy.restype = None
            library.opus_encode.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            library.opus_encode.restype = ctypes.c_int
            library.opus_encoder_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            library.opus_encoder_ctl.restype = ctypes.c_int
            library.opus_decoder_create.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            library.opus_decoder_create.restype = ctypes.c_void_p
            library.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
            library.opus_decoder_destroy.restype = None
            library.opus_decode.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
            ]
            library.opus_decode.restype = ctypes.c_int
            library.opus_decoder_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int]
            library.opus_decoder_ctl.restype = ctypes.c_int
            cls._library = library
            return library
        except Exception as exc:
            cls._library_error = str(exc)
            return None


class OpusCodec:
    def __init__(self) -> None:
        self.available = False
        self.last_error = ""
        self._encoder = None
        self._decoder = None
        self._library = _NativeOpusLibrary.load()
        if self._library is None:
            self.last_error = _NativeOpusLibrary._library_error or "opus_library_unavailable"
            return
        try:
            encoder_error = ctypes.c_int()
            decoder_error = ctypes.c_int()
            self._encoder = self._library.opus_encoder_create(
                OPUS_ENCODE_SAMPLE_RATE,
                OPUS_CHANNELS,
                OPUS_APPLICATION_VOIP,
                ctypes.byref(encoder_error),
            )
            self._decoder = self._library.opus_decoder_create(
                OPUS_DECODE_SAMPLE_RATE,
                OPUS_CHANNELS,
                ctypes.byref(decoder_error),
            )
            if encoder_error.value != 0 or decoder_error.value != 0 or not self._encoder or not self._decoder:
                raise RuntimeError(f"opus init failed encoder={encoder_error.value} decoder={decoder_error.value}")
            result = self._library.opus_encoder_ctl(self._encoder, OPUS_SET_INBAND_FEC, 0)
            if result < 0:
                raise RuntimeError(f"opus encoder ctl failed: {result}")
            self.available = True
        except Exception as exc:
            self.last_error = str(exc)
            self._destroy_native()
            self.available = False

    def encode(self, pcm_bytes: bytes) -> tuple[str, bytes]:
        if not pcm_bytes:
            return "pcm16", pcm_bytes
        if not self.available or self._encoder is None or self._library is None:
            return "pcm16", pcm_bytes
        try:
            input_buffer = ctypes.create_string_buffer(pcm_bytes, len(pcm_bytes))
            output_buffer = ctypes.create_string_buffer(OPUS_MAX_PACKET_BYTES)
            encoded_length = self._library.opus_encode(
                self._encoder,
                ctypes.cast(input_buffer, ctypes.c_void_p),
                OPUS_ENCODE_FRAME_SIZE,
                ctypes.cast(output_buffer, ctypes.c_void_p),
                OPUS_MAX_PACKET_BYTES,
            )
            if encoded_length < 0:
                raise RuntimeError(f"opus encode failed: {encoded_length}")
            return "opus", output_buffer.raw[:encoded_length]
        except Exception as exc:
            self.last_error = str(exc)
            return "pcm16", pcm_bytes

    def decode(
        self,
        codec: str,
        payload: bytes,
        *,
        missing_packets: int = 0,
        new_transmission: bool = False,
    ) -> bytes:
        del missing_packets
        if not payload:
            return payload
        normalized = codec.strip().lower()
        if normalized == "pcm16":
            if OPUS_ENCODE_SAMPLE_RATE != OPUS_DECODE_SAMPLE_RATE:
                converted, _ = audioop.ratecv(
                    payload,
                    2,
                    OPUS_CHANNELS,
                    OPUS_ENCODE_SAMPLE_RATE,
                    OPUS_DECODE_SAMPLE_RATE,
                    None,
                )
                return converted
            return payload
        if normalized != "opus":
            return payload
        if not self.available or self._decoder is None or self._library is None:
            return payload
        try:
            if new_transmission:
                self._library.opus_decoder_ctl(self._decoder, OPUS_RESET_STATE)
            input_buffer = ctypes.create_string_buffer(payload, len(payload))
            output_buffer = ctypes.create_string_buffer(OPUS_DECODE_FRAME_SIZE * 2)
            frame_count = self._library.opus_decode(
                self._decoder,
                ctypes.cast(input_buffer, ctypes.c_void_p),
                len(payload),
                ctypes.cast(output_buffer, ctypes.c_void_p),
                OPUS_DECODE_FRAME_SIZE,
                0,
            )
            if frame_count < 0:
                raise RuntimeError(f"opus decode failed: {frame_count}")
            decoded_length = frame_count * 2
            return output_buffer.raw[:decoded_length]
        except Exception as exc:
            self.last_error = str(exc)
            return payload

    def close(self) -> None:
        self._destroy_native()
        self.available = False

    def _destroy_native(self) -> None:
        if self._library is None:
            return
        if self._encoder:
            self._library.opus_encoder_destroy(self._encoder)
            self._encoder = None
        if self._decoder:
            self._library.opus_decoder_destroy(self._decoder)
            self._decoder = None
