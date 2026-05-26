from __future__ import annotations

import asyncio
import contextlib

from client.audio.device_registry import resolve_audio_device
from client.audio.wasapi_playback_host import WasapiPlaybackHostProcess


def _safe_import_audio_modules():
    try:
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore
    except Exception:
        return None, None
    return np, sd


class SpeakerPlaybackService:
    def __init__(self, sample_rate: int = 48_000, channels: int = 2) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device_index: int | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=192)
        self._stream = None
        self._task: asyncio.Task[None] | None = None
        self.running = False
        self.last_error = ""
        self.active_device_index: int | None = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""
        self.active_backend_name = "legacy-portaudio"
        self.device_name = ""
        self.device_endpoint_id = ""
        self._native_host = WasapiPlaybackHostProcess(sample_rate=sample_rate, channels=channels)
        self.prefer_native_host = False

    def configure(
        self,
        *,
        device_index: int | None,
        device_name: str = "",
        device_endpoint_id: str = "",
    ) -> None:
        self.device_index = device_index
        self.device_name = device_name.strip()
        self.device_endpoint_id = device_endpoint_id.strip()
        self._native_host.configure(
            device_index=device_index,
            device_name=self.device_name,
            device_endpoint_id=self.device_endpoint_id,
        )

    async def start(self) -> None:
        if self.prefer_native_host and self._native_host.available():
            try:
                await self._native_host.start()
                self.running = True
                self.last_error = ""
                self.active_device_index = self._native_host.active_device_index
                self.active_device_name = self._native_host.active_device_name
                self.active_device_endpoint_id = self._native_host.active_device_endpoint_id
                self.active_host_api_name = self._native_host.active_host_api_name
                self.active_backend_name = "native-wasapi"
                return
            except Exception as exc:
                self.last_error = str(exc)
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._playback_loop())

    async def stop(self) -> None:
        if self._native_host.running:
            await self._native_host.stop()
            self.running = False
            self.active_device_index = None
            self.active_device_name = "default"
            self.active_device_endpoint_id = ""
            self.active_host_api_name = ""
            self.active_backend_name = "legacy-portaudio"
            return
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.running = False
        self.active_device_index = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""
        self.active_backend_name = "legacy-portaudio"

    async def enqueue(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        if self._native_host.running:
            await self._native_host.enqueue(pcm_bytes)
            return
        if self._queue.full():
            _ = self._queue.get_nowait()
        await self._queue.put(pcm_bytes)

    async def _playback_loop(self) -> None:
        np, sd = _safe_import_audio_modules()
        if np is None or sd is None:
            return

        resolved_device = resolve_audio_device(
            "output",
            preferred_endpoint_id=self.device_endpoint_id,
            preferred_name=self.device_name,
            preferred_index=self.device_index,
        )
        resolved_device_index = self._resolve_device_index(sd)
        device_info = self._query_device_info(sd, resolved_device_index)
        host_api_name = self._host_api_name(sd, device_info)
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=resolved_device_index,
            blocksize=int(self.sample_rate * 0.04),
            latency="high",
            extra_settings=self._stream_extra_settings(sd, host_api_name),
        )
        self._stream.start()
        self.running = True
        self.last_error = ""
        self.active_device_index = resolved_device_index
        self.active_device_name = self._device_name(device_info)
        self.active_device_endpoint_id = resolved_device.endpoint_id if resolved_device is not None else ""
        self.active_host_api_name = host_api_name
        self.active_backend_name = "legacy-portaudio"
        try:
            while True:
                pcm_bytes = await self._queue.get()
                pcm = np.frombuffer(pcm_bytes, dtype=np.float32)
                if self.channels > 1:
                    pcm = pcm.reshape(-1, self.channels)
                await asyncio.to_thread(self._stream.write, pcm)
        except Exception as exc:
            self.last_error = str(exc)
            self.running = False
            raise
        finally:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            self.running = False

    def _resolve_device_index(self, sd):  # noqa: ANN001
        resolved_device = resolve_audio_device(
            "output",
            preferred_endpoint_id=self.device_endpoint_id,
            preferred_name=self.device_name,
            preferred_index=self.device_index,
        )
        if resolved_device is None:
            return None
        try:
            devices = sd.query_devices()
        except Exception:
            return None
        resolved_index = resolved_device.index
        if not isinstance(resolved_index, int):
            return None
        if resolved_index < 0 or resolved_index >= len(devices):
            return None
        try:
            if int(devices[resolved_index].get("max_output_channels", 0)) <= 0:
                return None
        except Exception:
            return None
        return resolved_index

    def _query_device_info(self, sd, device_index):  # noqa: ANN001
        try:
            if device_index is None:
                return sd.query_devices(kind="output")
            return sd.query_devices(device_index)
        except Exception:
            return {}

    def _device_name(self, device_info: object) -> str:
        try:
            raw_name = str(getattr(device_info, "get", lambda *_args, **_kwargs: "default")("name", "default"))
        except Exception:
            return "default"
        return raw_name.split("[", 1)[0].strip() or "default"

    def _host_api_name(self, sd, device_info: object) -> str:  # noqa: ANN001
        try:
            host_apis = sd.query_hostapis()
            host_index = int(getattr(device_info, "get", lambda *_args, **_kwargs: -1)("hostapi", -1))
            if 0 <= host_index < len(host_apis):
                return str(host_apis[host_index].get("name", ""))
        except Exception:
            return ""
        return ""

    def _stream_extra_settings(self, sd, host_api_name: str):  # noqa: ANN001
        if host_api_name != "Windows WASAPI" or not hasattr(sd, "WasapiSettings"):
            return None
        try:
            return sd.WasapiSettings(exclusive=False, auto_convert=True, explicit_sample_format=False)
        except Exception:
            return None
