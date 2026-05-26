from __future__ import annotations

import asyncio
import audioop
from collections.abc import Awaitable, Callable

from client.audio.device_registry import resolve_audio_device
from client.audio.wasapi_capture_host import WasapiCaptureHostProcess


FrameHandler = Callable[[bytes], Awaitable[None] | None]
LevelHandler = Callable[[float], None]


def _safe_import_audio_modules():
    try:
        import sounddevice as sd  # type: ignore
    except Exception:
        return None
    return sd


class MicrophoneCaptureService:
    def __init__(
        self,
        sample_rate: int = 48_000,
        channels: int = 1,
        block_size: int = 960,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size
        self.device_index: int | None = None
        self.volume_percent = 100
        self._stream = None
        self._frame_handler: FrameHandler | None = None
        self._level_handler: LevelHandler | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._smoothed_level = 0.0
        self.running = False
        self.last_error = ""
        self._stream_sample_rate = sample_rate
        self._stream_block_size = block_size
        self._ratecv_state = None
        self.active_device_index: int | None = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""
        self.active_backend_name = "legacy-portaudio"
        self.device_name = ""
        self.device_endpoint_id = ""
        self._resolved_device_endpoint_id = ""
        self._native_host = WasapiCaptureHostProcess(sample_rate=sample_rate, block_size=block_size)
        self.prefer_native_host = False

    def configure(
        self,
        device_index: int | None,
        device_name: str,
        device_endpoint_id: str,
        volume_percent: int,
        frame_handler: FrameHandler | None,
        level_handler: LevelHandler | None = None,
    ) -> None:
        self.device_index = device_index
        self.device_name = device_name.strip()
        self.device_endpoint_id = device_endpoint_id.strip()
        self.volume_percent = max(0, volume_percent)
        self._frame_handler = frame_handler
        self._level_handler = level_handler

    async def start(self) -> None:
        if self._stream is not None:
            return

        self._native_host.configure(
            device_index=self.device_index,
            device_name=self.device_name,
            device_endpoint_id=self.device_endpoint_id,
            frame_handler=self._frame_handler,
            level_handler=self._level_handler,
        )
        if self.prefer_native_host and self._native_host.available():
            try:
                await self._native_host.start()
                self.active_device_index = self._native_host.active_device_index
                self.active_device_name = self._native_host.active_device_name
                self.active_device_endpoint_id = self._native_host.active_device_endpoint_id
                self.active_host_api_name = self._native_host.active_host_api_name
                self.active_backend_name = "native-wasapi"
                self._stream_sample_rate = self.sample_rate
                self._stream_block_size = self.block_size
                self.running = True
                self.last_error = ""
                return
            except Exception as exc:
                self.last_error = str(exc)

        sd = _safe_import_audio_modules()
        if sd is None:
            self.last_error = "sounddevice_import_failed"
            return

        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            del time_info
            if frames <= 0:
                return

            payload = bytes(indata)

            if self._level_handler is not None:
                if payload:
                    rms = audioop.rms(payload, 2) / 32767.0
                    peak = audioop.max(payload, 2) / 32767.0
                    instant_level = max(rms * 2.8, peak * 0.9)
                else:
                    instant_level = 0.0
                instant_level = max(0.0, min(1.0, instant_level))
                self._smoothed_level = (self._smoothed_level * 0.72) + (instant_level * 0.28)
                self._loop.call_soon_threadsafe(self._level_handler, self._smoothed_level)

            if self._frame_handler is None:
                return

            if self._stream_sample_rate != self.sample_rate:
                payload, self._ratecv_state = audioop.ratecv(
                    payload,
                    2,
                    self.channels,
                    self._stream_sample_rate,
                    self.sample_rate,
                    self._ratecv_state,
                )
            result = self._frame_handler(payload)
            if asyncio.iscoroutine(result):
                asyncio.run_coroutine_threadsafe(result, self._loop)

        start_errors: list[str] = []
        for resolved_device_index in self._candidate_input_indexes(sd):
            device_info = self._query_device_info(sd, resolved_device_index)
            device_name = self._device_name(device_info)
            host_api_name = self._host_api_name(sd, device_info)
            for candidate_sample_rate in self._candidate_sample_rates(device_info):
                candidate_block_size = self._block_size_for_sample_rate(candidate_sample_rate)
                self._ratecv_state = None
                for attempt in self._stream_open_attempts(sd, host_api_name):
                    try:
                        self._stream = sd.RawInputStream(
                            samplerate=candidate_sample_rate,
                            channels=self.channels,
                            dtype="int16",
                            blocksize=candidate_block_size,
                            device=resolved_device_index,
                            latency="high",
                            extra_settings=attempt["extra_settings"],
                            never_drop_input=attempt["never_drop_input"],
                            callback=callback,
                        )
                        self._stream.start()
                        self._stream_sample_rate = candidate_sample_rate
                        self._stream_block_size = candidate_block_size
                        self.active_device_index = resolved_device_index
                        self.active_device_name = device_name
                        self.active_device_endpoint_id = self._resolved_device_endpoint_id
                        self.active_host_api_name = host_api_name
                        self.active_backend_name = "legacy-portaudio"
                        self.running = True
                        self.last_error = ""
                        return
                    except Exception as exc:
                        self._stream = None
                        self.running = False
                        attempt_label = attempt["label"]
                        start_errors.append(
                            f"{device_name or 'default'} via {host_api_name or 'default'} @ "
                            f"{candidate_sample_rate}Hz ({attempt_label}): {exc}"
                        )

        self.active_device_index = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""
        self.last_error = start_errors[-1] if start_errors else "no_compatible_input_stream"
        raise RuntimeError(self.last_error)

    async def stop(self) -> None:
        if self._native_host.running:
            await self._native_host.stop()
            self.running = False
            self._ratecv_state = None
            self.active_device_index = None
            self.active_device_name = "default"
            self.active_device_endpoint_id = ""
            self.active_host_api_name = ""
            self.active_backend_name = "legacy-portaudio"
            return
        if self._stream is None:
            self.running = False
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self.running = False
        self._ratecv_state = None
        self.active_device_index = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""
        self.active_backend_name = "legacy-portaudio"

    def _candidate_input_indexes(self, sd):  # noqa: ANN001
        resolved_device = resolve_audio_device(
            "input",
            preferred_endpoint_id=self.device_endpoint_id,
            preferred_name=self.device_name,
            preferred_index=self.device_index,
        )
        if resolved_device is None:
            if not isinstance(self.device_index, int):
                self._resolved_device_endpoint_id = ""
                return [None]
            resolved_index = self.device_index
            self._resolved_device_endpoint_id = ""
        else:
            resolved_index = resolved_device.index
            self._resolved_device_endpoint_id = resolved_device.endpoint_id
        try:
            devices = sd.query_devices()
        except Exception:
            return [None]
        selected_index = resolved_index
        if not isinstance(selected_index, int):
            return [None]
        if selected_index < 0 or selected_index >= len(devices):
            return [None]
        selected = devices[selected_index]
        try:
            if int(selected.get("max_input_channels", 0)) <= 0:
                return [None]
        except Exception:
            return [None]

        selected_name = _normalize_name(str(selected.get("name", "")))
        if not selected_name:
            selected_name = _normalize_name(self.device_name or (resolved_device.name if resolved_device is not None else ""))
        if not selected_name:
            return [selected_index]

        candidates: list[tuple[int, int]] = []
        for index, device_info in enumerate(devices):
            try:
                if int(device_info.get("max_input_channels", 0)) <= 0:
                    continue
            except Exception:
                continue
            if _normalize_name(str(device_info.get("name", ""))) != selected_name:
                continue
            candidates.append((self._capture_host_rank(self._host_api_name(sd, device_info)), index))
        if not candidates:
            return [selected_index]
        return [index for _rank, index in sorted(candidates)]

    def _candidate_sample_rates(self, device_info: object) -> list[int]:
        preferred_rates = [48_000, 44_100, 32_000, self.sample_rate]
        seen: set[int] = set()
        ordered: list[int] = []

        for rate in preferred_rates:
            if rate <= 0 or rate in seen:
                continue
            seen.add(rate)
            ordered.append(rate)

        default_rate = self._device_default_sample_rate(device_info)
        if default_rate > 0 and default_rate not in seen:
            ordered.append(default_rate)
        return ordered

    def _device_default_sample_rate(self, device_info: object) -> int:
        try:
            default_rate = float(getattr(device_info, "get", lambda *_args, **_kwargs: self.sample_rate)("default_samplerate", self.sample_rate))
        except Exception:
            return self.sample_rate
        if default_rate <= 1000:
            return self.sample_rate
        return int(round(default_rate))

    def _block_size_for_sample_rate(self, stream_sample_rate: int) -> int:
        frame_duration = self.block_size / float(self.sample_rate)
        return max(1, int(round(stream_sample_rate * frame_duration)))

    def _query_device_info(self, sd, device_index):  # noqa: ANN001
        try:
            if device_index is None:
                return sd.query_devices(kind="input")
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

    def _capture_host_rank(self, host_api_name: str) -> int:
        compatibility_first = {
            "Windows WASAPI": 0,
            "Windows DirectSound": 1,
            "MME": 2,
            "Windows WDM-KS": 3,
        }
        return compatibility_first.get(host_api_name, 99)

    def _stream_extra_settings(self, sd, host_api_name: str):  # noqa: ANN001
        if host_api_name != "Windows WASAPI" or not hasattr(sd, "WasapiSettings"):
            return None
        try:
            return sd.WasapiSettings(exclusive=False, auto_convert=True, explicit_sample_format=False)
        except Exception:
            return None

    def _stream_open_attempts(self, sd, host_api_name: str) -> list[dict[str, object]]:  # noqa: ANN001
        wasapi_settings = self._stream_extra_settings(sd, host_api_name)
        if host_api_name == "Windows WASAPI":
            attempts = []
            if wasapi_settings is not None:
                attempts.append(
                    {
                        "label": "wasapi_auto_convert",
                        "extra_settings": wasapi_settings,
                        "never_drop_input": False,
                    }
                )
            attempts.append(
                {
                    "label": "plain",
                    "extra_settings": None,
                    "never_drop_input": False,
                }
            )
            return attempts
        return [
            {
                "label": "plain",
                "extra_settings": None,
                "never_drop_input": False,
            }
        ]


def _normalize_name(raw_name: str) -> str:
    name = raw_name.strip()
    if "[" in name:
        name = name.split("[", 1)[0].strip()
    name = " ".join(name.split())
    return name.lower()
