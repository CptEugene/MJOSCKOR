from __future__ import annotations

import ctypes
import os
from pathlib import Path

from shared.constants.paths import runtime_paths


SPEEX_SET_DENOISE = 0
SPEEX_SET_AGC = 2
SPEEX_SET_AGC_LEVEL = 6
SPEEX_SET_NOISE_SUPPRESS = 18
SPEEX_SET_AGC_INCREMENT = 26
SPEEX_SET_AGC_DECREMENT = 28
SPEEX_SET_AGC_MAX_GAIN = 30
SPEEX_SET_AGC_TARGET = 46


def _candidate_dll_paths() -> list[Path]:
    paths = runtime_paths()
    candidates = [
        paths.bin_dir / "speexdsp.dll",
        paths.assets_dir / "bin" / "speexdsp.dll",
        Path(__file__).resolve().parents[3] / "_refs" / "DCS-SimpleRadioStandalone" / "DCS-SR-Client" / "speexdsp.dll",
    ]
    return [candidate for candidate in candidates if candidate.exists()]


def _prepare_speex_environment() -> None:
    for dll_path in _candidate_dll_paths():
        parent = str(dll_path.parent)
        try:
            os.add_dll_directory(parent)
        except (AttributeError, FileNotFoundError):
            pass
        current_path = os.environ.get("PATH", "")
        if parent.lower() not in current_path.lower():
            os.environ["PATH"] = parent + os.pathsep + current_path


class SpeexPreprocessor:
    _library: ctypes.WinDLL | None = None
    _library_error: str | None = None

    def __init__(
        self,
        frame_size: int,
        sample_rate: int,
        *,
        denoise: bool = True,
        denoise_attenuation: int = -30,
        agc_enabled: bool = False,
        agc_target: int | None = None,
        agc_increment: int | None = None,
        agc_decrement: int | None = None,
        agc_max_gain: int | None = None,
    ) -> None:
        self.frame_size = frame_size
        self.sample_rate = sample_rate
        self._state = None
        self.available = False
        self.last_error = ""
        self._denoise = denoise
        self._denoise_attenuation = denoise_attenuation
        self._agc_enabled = agc_enabled
        self._agc_target = agc_target
        self._agc_increment = agc_increment
        self._agc_decrement = agc_decrement
        self._agc_max_gain = agc_max_gain
        library = self._load_library()
        if library is None:
            self.last_error = self._library_error or "speexdsp_unavailable"
            return
        self._state = library.speex_preprocess_state_init(frame_size, sample_rate)
        if not self._state:
            self.last_error = "speexdsp_init_failed"
            return
        self.available = True
        self._configure_defaults()

    @classmethod
    def _load_library(cls):
        if cls._library is not None:
            return cls._library
        if cls._library_error is not None:
            return None
        try:
            _prepare_speex_environment()
            library = ctypes.WinDLL("speexdsp.dll")
            library.speex_preprocess_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
            library.speex_preprocess_state_init.restype = ctypes.c_void_p
            library.speex_preprocess_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            library.speex_preprocess_ctl.restype = ctypes.c_int
            library.speex_preprocess_run.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            library.speex_preprocess_run.restype = ctypes.c_int
            library.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
            library.speex_preprocess_state_destroy.restype = None
            cls._library = library
            return library
        except Exception as exc:
            cls._library_error = str(exc)
            return None

    def _configure_defaults(self) -> None:
        self._ctl_int(SPEEX_SET_DENOISE, 1 if self._denoise else 0)
        self._ctl_int(SPEEX_SET_NOISE_SUPPRESS, self._denoise_attenuation)
        self._ctl_int(SPEEX_SET_AGC, 1 if self._agc_enabled else 0)
        if self._agc_target is not None:
            self._ctl_int(SPEEX_SET_AGC_TARGET, self._agc_target)
        if self._agc_increment is not None:
            self._ctl_int(SPEEX_SET_AGC_INCREMENT, self._agc_increment)
        if self._agc_decrement is not None:
            self._ctl_int(SPEEX_SET_AGC_DECREMENT, self._agc_decrement)
        if self._agc_max_gain is not None:
            self._ctl_int(SPEEX_SET_AGC_MAX_GAIN, self._agc_max_gain)

    def process_pcm16(self, pcm_bytes: bytes) -> bytes:
        if not self.available or self._state is None or not pcm_bytes:
            return pcm_bytes
        if len(pcm_bytes) != self.frame_size * 2:
            return pcm_bytes
        buffer = ctypes.create_string_buffer(pcm_bytes, len(pcm_bytes))
        try:
            self._library.speex_preprocess_run(self._state, ctypes.cast(buffer, ctypes.c_void_p))
        except Exception as exc:
            self.last_error = str(exc)
            return pcm_bytes
        return buffer.raw

    def process_stream_pcm16(self, pcm_bytes: bytes) -> bytes:
        if not self.available or not pcm_bytes:
            return pcm_bytes
        frame_bytes = self.frame_size * 2
        if frame_bytes <= 0:
            return pcm_bytes
        if len(pcm_bytes) == frame_bytes:
            return self.process_pcm16(pcm_bytes)
        output = bytearray()
        for offset in range(0, len(pcm_bytes), frame_bytes):
            chunk = pcm_bytes[offset : offset + frame_bytes]
            if len(chunk) != frame_bytes:
                output.extend(chunk)
                continue
            output.extend(self.process_pcm16(chunk))
        return bytes(output)

    def close(self) -> None:
        if self._state is None or self._library is None:
            return
        self._library.speex_preprocess_state_destroy(self._state)
        self._state = None
        self.available = False

    def _ctl_int(self, command: int, value: int) -> None:
        if self._state is None or self._library is None:
            return
        raw_value = ctypes.c_int(value)
        result = self._library.speex_preprocess_ctl(self._state, command, ctypes.byref(raw_value))
        if result != 0:
            raise RuntimeError(f"speex ctl {command} failed with code {result}")
