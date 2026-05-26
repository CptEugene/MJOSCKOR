from __future__ import annotations

import asyncio
import math
import os
import threading
from array import array
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from time import monotonic

from client.audio.device_registry import list_audio_devices
from client.audio.effects import rx_end_tone, rx_start_tone, tx_end_tone, tx_start_tone
from client.audio.microphone_capture import MicrophoneCaptureService
from client.audio.output_limiter import OutputLimiter
from client.audio.radio_eq import Arc210RxProcessor
from client.audio.speaker_playback import SpeakerPlaybackService
from client.audio.speex_preprocessor import SpeexPreprocessor
from client.audio.talker_buffer import TalkerAudioBuffer
from client.audio.wasapi_audio_engine import WasapiAudioEngineProcess
from client.models.audio import AudioRuntimeState, AudioSettings, VoiceFrame
from client.network.voice_transport import VoiceTransportClient
from shared.constants.paths import runtime_paths
from shared.models.fleet_tree import ROLE_PERMISSIONS, RoleName


class AudioRuntime:
    def __init__(self) -> None:
        self.settings = AudioSettings()
        self.state = AudioRuntimeState()
        self._voice_effects_enabled = True
        self.capture = MicrophoneCaptureService()
        self.capture.prefer_native_host = True
        self.playback = SpeakerPlaybackService()
        self.transport = VoiceTransportClient()
        self.engine = WasapiAudioEngineProcess()
        self._native_engine_enabled = self._native_audio_engine_enabled()
        self._started = False
        self._channel_receive_activity: dict[str, float] = {}
        self._receive_monitor_task = None
        self._playout_task = None
        self._playout_wakeup = asyncio.Event()
        self._effect_chunks: deque[bytes] = deque(maxlen=128)
        self._talker_buffers: dict[int, TalkerAudioBuffer] = {}
        self._talker_channels: dict[int, str] = {}
        self._talker_roles: dict[int, str] = {}
        self._talker_rx_preprocessors: dict[int, SpeexPreprocessor] = {}
        self._channel_rx_processors: dict[str, Arc210RxProcessor] = {}
        self._legacy_packet_numbers: dict[int, int] = {}
        self._tx_preroll_frames: deque[bytes] = deque(maxlen=3)
        self._tx_speex = SpeexPreprocessor(frame_size=self.capture.block_size, sample_rate=self.capture.sample_rate)
        self._tx_ptt_pressed = False
        self._flush_tx_preroll = False
        self._tx_release_frame_count = 5
        self._tx_release_frames_remaining = 0
        self._tx_release_frames_sent_pending = 0
        self._tx_end_tone_pending = False
        self._tx_live_frames_sent = 0
        self._tx_release_watchdog_task: asyncio.Task[None] | None = None
        self._tx_worker_thread: threading.Thread | None = None
        self._tx_worker_stop = threading.Event()
        self._tx_queue: Queue[bytes | None] = Queue(maxsize=12)
        self._tx_state_lock = threading.Lock()
        self._last_capture_frame_at = 0.0
        self._last_tx_send_at = 0.0
        self._last_tx_queue_drop_log_at = 0.0
        self._last_tx_send_fail_log_at = 0.0
        self._last_microphone_level_event_at = 0.0
        self._level_meter_started_at = 0.0
        self._last_playout_empty_log_at = 0.0
        self._runtime_loop: asyncio.AbstractEventLoop | None = None
        self._selected_role = RoleName.SOLDIER
        self._slot_joined = False
        self._heard_talker_lock = threading.Lock()
        self._heard_talkers: dict[int, tuple[str, float]] = {}
        self._meter_enabled = False
        self._meter_capture_fallback_active = False
        self._level_meter_watchdog_task: asyncio.Task[None] | None = None
        self._output_limiter = OutputLimiter()
        self._audio_log_path = self._resolve_audio_log_path()
        self.engine.set_level_handler(self._update_microphone_level)
        self.engine.set_talker_handler(self._handle_engine_talker_state)
        self.engine.set_error_handler(self._handle_engine_error)

    def meter_enabled(self) -> bool:
        return self._meter_enabled

    def refresh_devices(self) -> AudioRuntimeState:
        inputs, outputs = list_audio_devices()
        self.state.input_devices = inputs
        self.state.output_devices = outputs
        return self.state

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._runtime_loop = asyncio.get_running_loop()
        if not self._tx_speex.available:
            self._tx_speex = SpeexPreprocessor(frame_size=self.capture.block_size, sample_rate=self.capture.sample_rate)
        self.state.last_error = ""
        try:
            if self._native_engine_enabled and self.engine.available():
                await self._stop_standalone_capture_before_native_engine()
                if await self._start_native_engine():
                    return

            self._configure_capture()
            self.playback.configure(
                device_index=self.settings.speaker_device_index,
                device_name=self.settings.speaker_device_name,
                device_endpoint_id=self.settings.speaker_device_endpoint_id,
            )
            self.transport.set_receive_handler(self._handle_received_frame)
            await self.playback.start()
            await self.transport.start()
            self._start_tx_worker()
            self._receive_monitor_task = asyncio.create_task(self._receive_monitor_loop())
            self._playout_task = asyncio.create_task(self._playout_loop())
            await self.capture.start()
            self._append_audio_log_line(
                "AUDIO start ok "
                f"mic_backend={self.capture.active_backend_name!r} "
                f"mic_device={self.capture.active_device_index} "
                f"mic_name={self.capture.active_device_name!r} "
                f"mic_endpoint={self.capture.active_device_endpoint_id!r} "
                f"mic_host={self.capture.active_host_api_name!r} "
                f"mic_rate={self.capture._stream_sample_rate} "
                f"mic_block={self.capture._stream_block_size} "
                f"speaker_backend={self.playback.active_backend_name!r} "
                f"speaker_device={self.playback.active_device_index} "
                f"speaker_name={self.playback.active_device_name!r} "
                f"speaker_endpoint={self.playback.active_device_endpoint_id!r} "
                f"speaker_host={self.playback.active_host_api_name!r} "
                "tx_processing='raw'"
            )
        except Exception as exc:
            self.state.last_error = str(exc)
            self._append_audio_log_line(f"AUDIO start failed: {exc}")
            self._started = False
            await self._safe_stop_runtime_components()

    async def stop(self) -> None:
        self._started = False
        self._runtime_loop = None
        if self.engine.running:
            await self.engine.stop()
        if self._receive_monitor_task is not None:
            self._receive_monitor_task.cancel()
            self._receive_monitor_task = None
        if self._playout_task is not None:
            self._playout_task.cancel()
            self._playout_task = None
        self._playout_wakeup.clear()
        self._effect_chunks.clear()
        self._talker_buffers.clear()
        self._talker_channels.clear()
        self._talker_roles.clear()
        for preprocessor in self._talker_rx_preprocessors.values():
            preprocessor.close()
        self._talker_rx_preprocessors.clear()
        self._channel_rx_processors.clear()
        self._channel_receive_activity.clear()
        self._legacy_packet_numbers.clear()
        self._tx_preroll_frames.clear()
        self._tx_ptt_pressed = False
        self._flush_tx_preroll = False
        self._tx_release_frames_remaining = 0
        self._tx_release_frames_sent_pending = 0
        self._tx_end_tone_pending = False
        self._tx_live_frames_sent = 0
        if self._tx_release_watchdog_task is not None:
            self._tx_release_watchdog_task.cancel()
            self._tx_release_watchdog_task = None
        if self._level_meter_watchdog_task is not None:
            self._level_meter_watchdog_task.cancel()
            self._level_meter_watchdog_task = None
        await self._stop_tx_worker()
        self._output_limiter.reset()
        await self.capture.stop()
        await self.transport.stop()
        await self.playback.stop()
        self._tx_speex.close()

    async def _start_native_engine(self) -> bool:
        self.engine.configure_devices(
            input_device_index=self.settings.microphone_device_index,
            input_device_name=self.settings.microphone_device_name,
            input_device_endpoint_id=self.settings.microphone_device_endpoint_id,
            output_device_index=self.settings.speaker_device_index,
            output_device_name=self.settings.speaker_device_name,
            output_device_endpoint_id=self.settings.speaker_device_endpoint_id,
        )
        self.engine.configure_transport(
            host=self.transport.host,
            port=self.transport.port,
            session_id=self.transport.session_id,
            channel_tag=self.transport.channel_tag,
        )
        self.engine.configure_role(self._selected_role.value)
        self.transport.configure_role(self._selected_role.value)
        self.engine.configure_levels(
            microphone_volume_percent=self.settings.microphone_volume_percent,
            speaker_volume_percent=self.settings.speaker_volume_percent,
            channel_receive_volumes=self.settings.channel_receive_volumes,
            channel_pan_modes=self.settings.channel_pan_modes,
        )
        try:
            await self.engine.start()
        except Exception as exc:
            self._append_audio_log_line(f"NATIVE ENGINE start failed, falling back to legacy audio: {exc}")
            await self.engine.stop()
            return False
        self._append_audio_log_line(
            "AUDIO start ok "
            f"mic_backend={self.engine.active_backend_name!r} "
            f"mic_device={self.engine.input_device_index} "
            f"mic_name={self.engine.active_input_device_name!r} "
            f"mic_endpoint={self.engine.active_input_device_endpoint_id!r} "
            f"mic_host={'Windows WASAPI'!r} "
            f"mic_rate={self.capture.sample_rate} "
            f"mic_block={self.capture.block_size} "
            f"speaker_backend={self.engine.active_backend_name!r} "
            f"speaker_device={self.engine.output_device_index} "
            f"speaker_name={self.engine.active_output_device_name!r} "
            f"speaker_endpoint={self.engine.active_output_device_endpoint_id!r} "
            f"speaker_host={'Windows WASAPI'!r} "
            "tx_processing='raw'"
        )
        if self._meter_enabled:
            self._schedule_level_meter_watchdog()
        return True

    async def start_transmit(self) -> None:
        if not self._slot_joined:
            return
        if self.engine.running:
            self.state.transmitting = True
            await self.engine.set_ptt(True, self.transport.channel_tag)
            return
        if self._started:
            await self._ensure_legacy_runtime_started()
        if hasattr(self.transport, "request_registration"):
            self.transport.request_registration(send_now=True)
        with self._tx_state_lock:
            if self._tx_ptt_pressed:
                return
        if self._started and not self.capture.running:
            try:
                await self.capture.start()
            except Exception as exc:
                self.state.last_error = str(exc)
                self._append_audio_log_line(f"PTT capture recovery failed: {exc}")
        with self._tx_state_lock:
            was_transmitting = self.state.transmitting
            self._tx_ptt_pressed = True
            self._tx_release_frames_remaining = 0
            self._tx_release_frames_sent_pending = 0
            self._tx_end_tone_pending = False
            self._tx_live_frames_sent = 0
        if self._tx_release_watchdog_task is not None:
            self._tx_release_watchdog_task.cancel()
            self._tx_release_watchdog_task = None
        if was_transmitting:
            return
        self.state.transmitting = True
        self._flush_tx_preroll = True
        if not self.capture.running:
            self._append_audio_log_line("PTT start requested while microphone capture is not running")
        await self._enqueue_effect(tx_start_tone(self.transport.channel_tag))

    async def stop_transmit(self) -> None:
        if self.engine.running:
            self.state.transmitting = False
            await self.engine.set_ptt(False, self.transport.channel_tag)
            return
        with self._tx_state_lock:
            self._tx_ptt_pressed = False
            transmitting = self.state.transmitting
            tx_live_frames_sent = self._tx_live_frames_sent
            if not transmitting:
                self._flush_tx_preroll = False
                return
        if tx_live_frames_sent <= 0:
            self._append_audio_log_line("PTT stop finished immediately because no microphone frames were captured")
            await self._finish_transmit_release()
            return
        with self._tx_state_lock:
            self._tx_release_frames_remaining = self._tx_release_frame_count
            self._tx_release_frames_sent_pending = 0
            self._tx_end_tone_pending = True
        if self._tx_release_watchdog_task is not None:
            self._tx_release_watchdog_task.cancel()
        self._tx_release_watchdog_task = asyncio.create_task(self._tx_release_watchdog())
        if self._tx_release_frame_count <= 0:
            await self._finish_transmit_release()

    async def start_level_meter(self) -> None:
        self._meter_enabled = True
        self.state.microphone_level = 0.0
        self._level_meter_started_at = monotonic()
        if self._started and not self.engine.running:
            self._append_audio_log_line("LEVEL METER requested while audio is starting; waiting for native engine")
            self._schedule_level_meter_watchdog()
            return
        self._append_audio_log_line(
            f"LEVEL METER start requested engine_running={self.engine.running} capture_running={self.capture.running}"
        )
        if self.engine.running:
            self._schedule_level_meter_watchdog()
            return
        self._configure_capture()
        try:
            await self.capture.start()
            self._meter_capture_fallback_active = True
            self._append_audio_log_line(
                "LEVEL METER capture started "
                f"backend={self.capture.active_backend_name!r} "
                f"device={self.capture.active_device_index} "
                f"name={self.capture.active_device_name!r} "
                f"endpoint={self.capture.active_device_endpoint_id!r}"
            )
            self._schedule_level_meter_watchdog()
        except Exception as exc:
            self.state.last_error = str(exc)
            self._append_audio_log_line(f"LEVEL METER start failed: {exc}")

    async def stop_level_meter(self) -> None:
        self._meter_enabled = False
        self.state.microphone_level = 0.0
        if self._level_meter_watchdog_task is not None:
            self._level_meter_watchdog_task.cancel()
            self._level_meter_watchdog_task = None
        if self._meter_capture_fallback_active:
            await self.capture.stop()
            self._meter_capture_fallback_active = False
            self._configure_capture()
            self._append_audio_log_line("LEVEL METER fallback capture stopped")
            return
        if self.engine.running:
            return
        self._configure_capture()
        if not self._started:
            await self.capture.stop()

    def apply_settings(self, settings: AudioSettings) -> None:
        self.settings = settings
        if self.engine.running:
            self.engine.configure_devices(
                input_device_index=settings.microphone_device_index,
                input_device_name=settings.microphone_device_name,
                input_device_endpoint_id=settings.microphone_device_endpoint_id,
                output_device_index=settings.speaker_device_index,
                output_device_name=settings.speaker_device_name,
                output_device_endpoint_id=settings.speaker_device_endpoint_id,
            )
            self.engine.configure_levels(
                microphone_volume_percent=settings.microphone_volume_percent,
                speaker_volume_percent=settings.speaker_volume_percent,
                channel_receive_volumes=settings.channel_receive_volumes,
                channel_pan_modes=settings.channel_pan_modes,
            )
        self._configure_capture()
        self.playback.configure(
            device_index=settings.speaker_device_index,
            device_name=settings.speaker_device_name,
            device_endpoint_id=settings.speaker_device_endpoint_id,
        )

    def configure_transport(self, host: str, session_id: int, channel_tag: str) -> None:
        self.transport.configure(host=host, session_id=session_id, channel_tag=channel_tag)
        if self.engine.running:
            self.engine.configure_transport(
                host=host,
                port=self.transport.port,
                session_id=session_id,
                channel_tag=channel_tag,
            )
            self._schedule_engine_sync()

    def set_channel_tag(self, channel_tag: str) -> None:
        self.transport.configure(
            host=self.transport.host,
            session_id=self.transport.session_id,
            channel_tag=channel_tag,
        )
        if self.engine.running:
            self.engine.configure_transport(
                host=self.transport.host,
                port=self.transport.port,
                session_id=self.transport.session_id,
                channel_tag=channel_tag,
            )
            self._schedule_engine_sync()

    def set_selected_role(self, role: str) -> None:
        self._selected_role = RoleName.coerce(role)
        self._channel_rx_processors.clear()
        self.engine.configure_role(self._selected_role.value)
        self.transport.configure_role(self._selected_role.value)
        if self.engine.running:
            self._schedule_engine_sync()

    def set_slot_joined(self, joined: bool) -> None:
        self._slot_joined = bool(joined)
        if joined:
            return
        with self._heard_talker_lock:
            self._heard_talkers.clear()
        self._channel_receive_activity.clear()
        self._talker_roles.clear()

    async def _handle_received_frame(self, frame: VoiceFrame) -> None:
        if not self._can_rx(frame.channel_tag):
            return
        if not frame.pcm_bytes:
            return
        now = monotonic()
        if frame.channel_tag not in self._channel_receive_activity:
            await self._enqueue_effect(rx_start_tone(frame.channel_tag))
        self._channel_receive_activity[frame.channel_tag] = now
        with self._heard_talker_lock:
            self._heard_talkers[frame.session_id] = (frame.channel_tag, now)
        if frame.new_transmission:
            self._talker_buffers.pop(frame.session_id, None)
        processed = frame.pcm_bytes
        await self._enqueue_voice(
            processed,
            frame.channel_tag,
            frame.session_id,
            self._resolved_packet_number(frame),
            sender_role=frame.sender_role or "Soldier",
            new_transmission=frame.new_transmission,
        )

    def _update_microphone_level(self, level: float) -> None:
        self._last_microphone_level_event_at = monotonic()
        if not self._meter_enabled:
            return
        self.state.microphone_level = level

    def _handle_engine_talker_state(self, session_id: int, channel_tag: str, active: bool) -> None:
        now = monotonic()
        with self._heard_talker_lock:
            if active:
                self._heard_talkers[session_id] = (channel_tag, now)
            else:
                self._heard_talkers.pop(session_id, None)

    def _handle_engine_error(self, message: str) -> None:
        self.state.last_error = message
        self._append_audio_log_line(f"NATIVE ENGINE error: {message}")

    def _schedule_engine_sync(self) -> None:
        loop = self._runtime_loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.engine.sync_configuration(), loop)
        except RuntimeError:
            return

    def _configure_capture(self) -> None:
        self.capture.configure(
            device_index=self.settings.microphone_device_index,
            device_name=self.settings.microphone_device_name,
            device_endpoint_id=self.settings.microphone_device_endpoint_id,
            volume_percent=self.settings.microphone_volume_percent,
            frame_handler=self._handle_captured_frame,
            level_handler=self._update_microphone_level if self._meter_enabled else None,
        )

    def _configure_meter_capture(self) -> None:
        self.capture.configure(
            device_index=self.settings.microphone_device_index,
            device_name=self.settings.microphone_device_name,
            device_endpoint_id=self.settings.microphone_device_endpoint_id,
            volume_percent=self.settings.microphone_volume_percent,
            frame_handler=None,
            level_handler=self._update_microphone_level,
        )

    def current_heard_talkers(self, max_age_seconds: float = 0.9) -> list[tuple[int, str]]:
        now = monotonic()
        with self._heard_talker_lock:
            expired = [
                session_id
                for session_id, (_channel_tag, last_heard) in self._heard_talkers.items()
                if (now - last_heard) > max_age_seconds
            ]
            for session_id in expired:
                self._heard_talkers.pop(session_id, None)
            return [
                (session_id, channel_tag)
                for session_id, (channel_tag, _last_heard) in self._heard_talkers.items()
            ]

    async def _send_processed_frame(self, pcm_bytes: bytes) -> None:
        # Test-only helper: exercise the same capture path, then drain the queue inline.
        if self._runtime_loop is None:
            self._runtime_loop = asyncio.get_running_loop()
        self._handle_captured_frame(pcm_bytes)
        await self._drain_tx_queue_for_testing()
        with self._tx_state_lock:
            should_finish_release = (
                self.state.transmitting
                and not self._tx_ptt_pressed
                and self._tx_release_frames_remaining <= 0
            )
        if should_finish_release:
            await self._finish_transmit_release()

    def _handle_captured_frame(self, pcm_bytes: bytes) -> None:
        now = monotonic()
        if self._last_capture_frame_at > 0.0:
            gap_ms = int((now - self._last_capture_frame_at) * 1000)
            if gap_ms >= 120 and self.state.transmitting:
                self._append_audio_log_line(f"DIAG TX capture gap {gap_ms}ms while transmitting")
        self._last_capture_frame_at = now
        prepared = self._prepare_tx_frame(pcm_bytes)
        if not prepared:
            return
        frames_to_send: list[bytes] = []
        flushed_frames = 0
        finish_release = False
        with self._tx_state_lock:
            if not self._tx_ptt_pressed and not self.state.transmitting:
                self._tx_preroll_frames.append(prepared)
                return
            if self._tx_ptt_pressed:
                if self._flush_tx_preroll:
                    while self._tx_preroll_frames:
                        frames_to_send.append(self._tx_preroll_frames.popleft())
                    flushed_frames = len(frames_to_send)
                    if flushed_frames:
                        self.state.tx_preroll_frames_sent += flushed_frames
                    self._flush_tx_preroll = False
                self._tx_live_frames_sent += 1
                frames_to_send.append(prepared)
            else:
                frames_to_send.append(prepared)
                self.state.tx_release_frames_sent += 1
                self._tx_release_frames_sent_pending += 1
                if self._tx_release_frames_remaining > 0:
                    self._tx_release_frames_remaining -= 1
                if self._tx_release_frames_remaining <= 0:
                    finish_release = True
        if flushed_frames:
            self._append_audio_log_line(f"TX preroll flushed {flushed_frames} frame(s) on PTT start")
        for frame in frames_to_send:
            self._enqueue_tx_frame(frame)
        if finish_release:
            self._schedule_finish_transmit_release()

    async def _receive_monitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.12)
                now = monotonic()
                stale_channels = [
                    channel_tag
                    for channel_tag, last_receive_at in self._channel_receive_activity.items()
                    if (now - last_receive_at) > 1.0
                ]
                for channel_tag in stale_channels:
                    await self._enqueue_effect(rx_end_tone(channel_tag))
                    self._channel_receive_activity.pop(channel_tag, None)
                    self._channel_rx_processors.pop(channel_tag, None)
        except asyncio.CancelledError:
            return

    async def _playout_loop(self) -> None:
        frame_duration = self.capture.block_size / float(self.capture.sample_rate)
        try:
            while True:
                if not self._has_pending_playout_audio():
                    await self._playout_wakeup.wait()
                    self._playout_wakeup.clear()
                else:
                    await asyncio.sleep(frame_duration)
                effect_streams, talker_streams = self._drain_ready_playout_frames()
                if not effect_streams and not talker_streams:
                    self._output_limiter.reset()
                    continue
                pending: list[list[float]] = [self._pcm16_to_float_stream(stream) for stream in effect_streams]
                for (channel_tag, sender_role), streams in talker_streams.items():
                    if not streams:
                        continue
                    mixed_channel = self._mix_float_streams([self._pcm16_to_float_stream(stream) for stream in streams])
                    if self._voice_effects_enabled:
                        processor_key = f"{sender_role.lower()}:{channel_tag}"
                        rx_processor = self._channel_rx_processors.get(processor_key)
                        if rx_processor is None:
                            rx_processor = Arc210RxProcessor(sender_role)
                            self._channel_rx_processors[processor_key] = rx_processor
                        mixed_channel = rx_processor.process_float_samples(mixed_channel)
                    mixed_channel = self._scale_float_stream(mixed_channel, gain=self._receive_gain(channel_tag))
                    pending.append(self._pan_float_stream(mixed_channel, self._channel_pan_mode(channel_tag)))
                mixed = self._limit_float_stream(self._mix_float_streams(pending))
                await self.playback.enqueue(self._float_stream_to_pcm32(mixed))
        except asyncio.CancelledError:
            return

    async def restart_live_streams(self) -> None:
        if self._meter_capture_fallback_active:
            await self.capture.stop()
            self._meter_capture_fallback_active = False
        if self.engine.running:
            await self.engine.stop()
            if self._started:
                self._started = False
            await self.start()
            return
        await self.capture.stop()
        await self.playback.stop()
        try:
            await self.playback.start()
            if self._started or self._meter_enabled:
                await self.capture.start()
        except Exception as exc:
            self.state.last_error = str(exc)
            self._append_audio_log_line(f"AUDIO restart failed: {exc}")

    async def _ensure_legacy_runtime_started(self) -> None:
        if self.engine.running:
            return
        if self._meter_capture_fallback_active:
            await self.capture.stop()
            self._meter_capture_fallback_active = False
        self._configure_capture()
        self.playback.configure(
            device_index=self.settings.speaker_device_index,
            device_name=self.settings.speaker_device_name,
            device_endpoint_id=self.settings.speaker_device_endpoint_id,
        )
        self.transport.set_receive_handler(self._handle_received_frame)
        if not self.playback.running:
            await self.playback.start()
        if getattr(self.transport, "_socket", None) is None:
            await self.transport.start()
            self._append_audio_log_line(
                "DIAG legacy voice transport started for fallback transmission"
            )
        self._start_tx_worker()
        if self._receive_monitor_task is None or self._receive_monitor_task.done():
            self._receive_monitor_task = asyncio.create_task(self._receive_monitor_loop())
        if self._playout_task is None or self._playout_task.done():
            self._playout_task = asyncio.create_task(self._playout_loop())

    async def _stop_standalone_capture_before_native_engine(self) -> None:
        if not self.capture.running:
            return
        await self.capture.stop()
        self._meter_capture_fallback_active = False
        self._append_audio_log_line(
            "AUDIO start stopped standalone microphone capture before native engine"
        )

    def _schedule_level_meter_watchdog(self) -> None:
        if self._level_meter_watchdog_task is not None:
            self._level_meter_watchdog_task.cancel()
        self._level_meter_watchdog_task = asyncio.create_task(self._level_meter_watchdog())

    async def _level_meter_watchdog(self) -> None:
        try:
            started_at = self._level_meter_started_at
            await asyncio.sleep(0.8)
            if not self._meter_enabled:
                return
            if self._last_microphone_level_event_at >= started_at:
                return
            if self.engine.running and not self.capture.running:
                self._append_audio_log_line(
                    "LEVEL METER did not receive native engine level events; starting fallback capture"
                )
                await self._start_meter_capture_fallback()
                await asyncio.sleep(1.0)
                if self._meter_enabled and self._last_microphone_level_event_at < started_at:
                    self._append_audio_log_line(
                        "LEVEL METER still has no microphone level events after fallback capture"
                    )
        except asyncio.CancelledError:
            return

    async def _start_meter_capture_fallback(self) -> None:
        if self.capture.running:
            return
        self._configure_meter_capture()
        try:
            await self.capture.start()
        except Exception as exc:
            self.state.last_error = str(exc)
            self._append_audio_log_line(f"LEVEL METER fallback capture failed: {exc}")
            return
        self._meter_capture_fallback_active = True
        self._append_audio_log_line(
            "LEVEL METER fallback capture started "
            f"backend={self.capture.active_backend_name!r} "
            f"device={self.capture.active_device_index} "
            f"name={self.capture.active_device_name!r} "
            f"endpoint={self.capture.active_device_endpoint_id!r}"
        )

    async def _enqueue_voice(
        self,
        pcm_bytes: bytes,
        channel_tag: str,
        session_id: int,
        packet_number: int,
        *,
        sender_role: str = "Soldier",
        new_transmission: bool = False,
    ) -> None:
        buffer = None if new_transmission else self._talker_buffers.get(session_id)
        if buffer is None:
            buffer = TalkerAudioBuffer(
                skip_threshold_packets=4,
                max_buffered_packets=72,
                max_concealed_packets=0,
                max_adaptive_packets=8,
                stable_packet_window=48,
            )
            self._talker_buffers[session_id] = buffer
        self._talker_channels[session_id] = channel_tag
        self._talker_roles[session_id] = sender_role or "Soldier"
        push_result = buffer.push(packet_number, pcm_bytes)
        if push_result == "late_drop":
            self._record_audio_drop(
                "rx_packets_late_dropped",
                f"RX late packet dropped for session {session_id} packet {packet_number}",
            )
        elif push_result == "overflow_drop":
            self._record_audio_drop(
                "rx_packets_overflow_dropped",
                f"RX talker buffer overflow while storing session {session_id} packet {packet_number}",
            )
        self._playout_wakeup.set()

    async def _enqueue_effect(self, pcm_bytes: bytes) -> None:
        if not self._voice_effects_enabled:
            return
        if not pcm_bytes:
            return
        scaled = self._pan_pcm16(self._scale_pcm16(pcm_bytes, gain=0.10 * self._speaker_output_gain()), "both")
        for chunk in self._split_stereo_chunks(scaled):
            if self._effect_chunks.maxlen is not None and len(self._effect_chunks) >= self._effect_chunks.maxlen:
                self._effect_chunks.popleft()
                self._record_audio_drop(
                    "effect_chunks_dropped",
                    "RX effect chunk dropped because the local effect queue was full",
                )
            self._effect_chunks.append(chunk)
        self._playout_wakeup.set()

    def _receive_gain(self, channel_tag: str) -> float:
        index_by_tag = {"squad": 0, "hq": 1, "atc": 2, "general": 3}
        slider_index = index_by_tag.get(channel_tag, 3)
        percent = 100
        if 0 <= slider_index < len(self.settings.channel_receive_volumes):
            percent = self.settings.channel_receive_volumes[slider_index]
        speaker_gain = self._speaker_output_gain()
        channel_gain = self._receive_slider_gain(percent)
        # Match the old "about 30%" listening level as the new 100% baseline,
        # but keep the slider dramatic by applying it after AGC.
        return max(0.0, channel_gain * speaker_gain * 0.42)

    def _can_rx(self, channel_tag: str) -> bool:
        if not self._slot_joined:
            return False
        channel_key = self._channel_key(channel_tag)
        if channel_key is None:
            return True
        return ROLE_PERMISSIONS[self._selected_role].channel(channel_key).rx

    def _channel_key(self, channel_tag: str) -> str | None:
        return {
            "squad": "ch1",
            "hq": "ch2",
            "atc": "ch3",
            "general": "ch4",
        }.get(channel_tag.strip().lower())

    def _channel_pan_mode(self, channel_tag: str) -> str:
        index_by_tag = {"squad": 0, "hq": 1, "atc": 2, "general": 3}
        index = index_by_tag.get(channel_tag, 3)
        if 0 <= index < len(self.settings.channel_pan_modes):
            return str(self.settings.channel_pan_modes[index]).lower()
        return "both"

    def _scale_pcm16(self, pcm_bytes: bytes, gain: float) -> bytes:
        if not pcm_bytes or gain == 1.0:
            return pcm_bytes
        sample_count = len(pcm_bytes) // 2
        output = bytearray(len(pcm_bytes))
        for index in range(sample_count):
            sample = int.from_bytes(pcm_bytes[index * 2 : index * 2 + 2], "little", signed=True)
            scaled = int(max(-32768, min(32767, round(sample * gain))))
            output[index * 2 : index * 2 + 2] = scaled.to_bytes(2, "little", signed=True)
        return bytes(output)

    def _apply_agc_pcm16(self, pcm_bytes: bytes, target_peak: float, max_gain: float) -> bytes:
        if not pcm_bytes:
            return pcm_bytes
        sample_count = len(pcm_bytes) // 2
        peak = 0
        for index in range(sample_count):
            sample = abs(int.from_bytes(pcm_bytes[index * 2 : index * 2 + 2], "little", signed=True))
            if sample > peak:
                peak = sample
        if peak <= 0:
            return pcm_bytes
        gain = min(max_gain, max(0.35, target_peak / float(peak)))
        smoothed_gain = math.sqrt(gain)
        return self._scale_pcm16(pcm_bytes, smoothed_gain)

    def _pan_pcm16(self, pcm_bytes: bytes, mode: str) -> bytes:
        if not pcm_bytes:
            return pcm_bytes
        output = bytearray()
        normalized_mode = mode.lower()
        for index in range(0, len(pcm_bytes), 2):
            sample = pcm_bytes[index : index + 2]
            if normalized_mode == "left":
                output.extend(sample)
                output.extend((0).to_bytes(2, "little", signed=True))
            elif normalized_mode == "right":
                output.extend((0).to_bytes(2, "little", signed=True))
                output.extend(sample)
            else:
                output.extend(sample)
                output.extend(sample)
        return bytes(output)

    def _mix_pcm16_streams(self, streams: list[bytes]) -> bytes:
        if not streams:
            return b""
        if len(streams) == 1:
            return streams[0]
        max_len = max(len(stream) for stream in streams)
        if max_len <= 0:
            return b""
        sample_count = max_len // 2
        mixed = bytearray(sample_count * 2)
        for sample_index in range(sample_count):
            total = 0
            offset = sample_index * 2
            for stream in streams:
                if offset + 2 > len(stream):
                    continue
                total += int.from_bytes(stream[offset : offset + 2], "little", signed=True)
            total = max(-32768, min(32767, total))
            mixed[offset : offset + 2] = int(total).to_bytes(2, "little", signed=True)
        return bytes(mixed)

    def _pcm16_to_float_stream(self, pcm_bytes: bytes) -> list[float]:
        if not pcm_bytes:
            return []
        samples: list[float] = []
        for offset in range(0, len(pcm_bytes), 2):
            sample = int.from_bytes(pcm_bytes[offset : offset + 2], "little", signed=True)
            samples.append(sample / 32768.0)
        return samples

    def _float_stream_to_pcm32(self, samples: list[float]) -> bytes:
        if not samples:
            return b""
        packed = array("f", samples)
        return packed.tobytes()

    def _scale_float_stream(self, samples: list[float], gain: float) -> list[float]:
        if not samples or gain == 1.0:
            return samples
        return [sample * gain for sample in samples]

    def _pan_float_stream(self, samples: list[float], mode: str) -> list[float]:
        if not samples:
            return []
        output: list[float] = []
        normalized_mode = mode.lower()
        for sample in samples:
            if normalized_mode == "left":
                output.extend((sample, 0.0))
            elif normalized_mode == "right":
                output.extend((0.0, sample))
            else:
                output.extend((sample, sample))
        return output

    def _mix_float_streams(self, streams: list[list[float]]) -> list[float]:
        if not streams:
            return []
        if len(streams) == 1:
            return list(streams[0])
        max_len = max(len(stream) for stream in streams)
        if max_len <= 0:
            return []
        mixed = [0.0] * max_len
        for stream in streams:
            for index, sample in enumerate(stream):
                mixed[index] += sample
        return mixed

    def _limit_float_stream(self, samples: list[float]) -> list[float]:
        if not samples:
            return []
        return self._output_limiter.process(samples)

    def _has_pending_playout_audio(self) -> bool:
        if self._effect_chunks:
            return True
        return any(buffer.has_pending() for buffer in self._talker_buffers.values())

    def _drain_ready_playout_frames(self) -> tuple[list[bytes], dict[tuple[str, str], list[bytes]]]:
        effect_streams: list[bytes] = []
        if self._effect_chunks:
            effect_streams.append(self._effect_chunks.popleft())
        talker_streams: dict[tuple[str, str], list[bytes]] = {}
        now = monotonic()
        stale_talkers: list[int] = []
        for session_id, buffer in list(self._talker_buffers.items()):
            frame, skipped_packets = buffer.pop_ready()
            if frame is not None:
                channel_tag = self._talker_channels.get(session_id, "general")
                sender_role = self._talker_roles.get(session_id, "Soldier")
                talker_streams.setdefault((channel_tag, sender_role), []).append(frame)
            if skipped_packets:
                self._record_audio_skip(skipped_packets, session_id)
                if not buffer.has_pending() and buffer.is_stale(1.2, now=now):
                    stale_talkers.append(session_id)
                elif frame is None and buffer.has_pending() and (now - self._last_playout_empty_log_at) >= 1.0:
                    self._last_playout_empty_log_at = now
                    self._append_audio_log_line(
                        f"DIAG RX playout waiting for buffered talker session {session_id}"
                    )
        for session_id in stale_talkers:
            self._talker_buffers.pop(session_id, None)
            self._talker_channels.pop(session_id, None)
            self._talker_roles.pop(session_id, None)
            preprocessor = self._talker_rx_preprocessors.pop(session_id, None)
            if preprocessor is not None:
                preprocessor.close()
            self._legacy_packet_numbers.pop(session_id, None)
        return effect_streams, talker_streams

    def _split_stereo_chunks(self, pcm_bytes: bytes) -> list[bytes]:
        if not pcm_bytes:
            return []
        frame_duration = self.capture.block_size / float(self.capture.sample_rate)
        playback_frame_samples = max(1, int(round(self.playback.sample_rate * frame_duration)))
        frame_bytes = playback_frame_samples * self.playback.channels * 2
        chunks: list[bytes] = []
        for offset in range(0, len(pcm_bytes), frame_bytes):
            chunk = pcm_bytes[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + (b"\x00" * (frame_bytes - len(chunk)))
            chunks.append(chunk)
        return chunks

    def _resolved_packet_number(self, frame: VoiceFrame) -> int:
        if frame.packet_number > 0:
            self._legacy_packet_numbers[frame.session_id] = frame.packet_number
            return frame.packet_number
        packet_number = self._legacy_packet_numbers.get(frame.session_id, 0) + 1
        self._legacy_packet_numbers[frame.session_id] = packet_number
        return packet_number

    def _prepare_tx_frame(self, pcm_bytes: bytes) -> bytes:
        pcm_bytes = self._scale_pcm16(pcm_bytes, gain=self._slider_gain(self.settings.microphone_volume_percent))
        return pcm_bytes

    def _speaker_output_gain(self) -> float:
        return self._receive_slider_gain(self.settings.speaker_volume_percent)

    def _receive_slider_gain(self, percent: int) -> float:
        normalized = max(0.0, percent / 100.0)
        if normalized <= 1.0:
            return normalized * normalized * normalized
        return min(8.0, 1.0 + ((normalized - 1.0) * 7.0))

    def _slider_gain(self, percent: int) -> float:
        normalized = max(0.0, percent / 100.0)
        if normalized <= 1.0:
            return normalized * normalized
        return min(4.0, 1.0 + ((normalized - 1.0) * 3.0))

    def _native_audio_engine_enabled(self) -> bool:
        value = os.environ.get("MAYDAY_NATIVE_AUDIO_ENGINE", "1").strip().lower()
        return value not in {"0", "false", "no", "off"}

    async def _finish_transmit_release(self) -> None:
        with self._tx_state_lock:
            if not self.state.transmitting:
                return
        if self._tx_release_watchdog_task is not None:
            self._tx_release_watchdog_task.cancel()
            self._tx_release_watchdog_task = None
        with self._tx_state_lock:
            self.state.transmitting = False
            self._flush_tx_preroll = False
            self._tx_release_frames_remaining = 0
            self._tx_live_frames_sent = 0
            tx_release_frames_sent_pending = self._tx_release_frames_sent_pending
            self._tx_release_frames_sent_pending = 0
            enqueue_end_tone = self._tx_end_tone_pending
            self._tx_end_tone_pending = False
        if tx_release_frames_sent_pending:
            self._append_audio_log_line(
                f"TX release tail sent {tx_release_frames_sent_pending} frame(s) before stop"
            )
        if enqueue_end_tone:
            await self._enqueue_effect(tx_end_tone(self.transport.channel_tag))

    async def _tx_release_watchdog(self) -> None:
        try:
            await asyncio.sleep(0.25)
            if not self._tx_ptt_pressed and self.state.transmitting:
                self._append_audio_log_line("TX release watchdog forced transmit stop after missing release frames")
                await self._finish_transmit_release()
        except asyncio.CancelledError:
            return

    def _resolve_audio_log_path(self) -> Path:
        paths = runtime_paths()
        paths.client_logs_dir.mkdir(parents=True, exist_ok=True)
        return paths.client_logs_dir / "audio.log"

    def _append_audio_log_line(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._audio_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {message}\n")

    def _increment_audio_counter(self, field_name: str, amount: int = 1) -> None:
        current = int(getattr(self.state, field_name))
        setattr(self.state, field_name, current + amount)

    def _record_audio_drop(self, field_name: str, message: str, amount: int = 1) -> None:
        self._increment_audio_counter(field_name, amount=amount)
        self._append_audio_log_line(message)

    def _record_audio_skip(self, skipped_packets: int, session_id: int) -> None:
        if skipped_packets <= 0:
            return
        self._increment_audio_counter("rx_packets_skipped", amount=skipped_packets)
        self._append_audio_log_line(
            f"RX skipped {skipped_packets} missing packet(s) while catching up talker session {session_id}"
        )

    async def _safe_stop_runtime_components(self) -> None:
        if self._receive_monitor_task is not None:
            self._receive_monitor_task.cancel()
            self._receive_monitor_task = None
        if self._playout_task is not None:
            self._playout_task.cancel()
            self._playout_task = None
        await self._stop_tx_worker()
        await self.capture.stop()
        await self.transport.stop()
        await self.playback.stop()

    def _start_tx_worker(self) -> None:
        if self._tx_worker_thread is not None and self._tx_worker_thread.is_alive():
            return
        self._tx_worker_stop.clear()
        self._clear_tx_queue()
        self._tx_worker_thread = threading.Thread(target=self._tx_worker_loop, name="MaydayTxWorker", daemon=True)
        self._tx_worker_thread.start()

    async def _stop_tx_worker(self) -> None:
        self._tx_worker_stop.set()
        self._enqueue_tx_sentinel()
        worker = self._tx_worker_thread
        self._tx_worker_thread = None
        if worker is not None and worker.is_alive():
            await asyncio.to_thread(worker.join, 1.0)
        self._clear_tx_queue()

    def _enqueue_tx_frame(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or self._tx_worker_stop.is_set():
            return
        worker = self._tx_worker_thread
        if self._started and (worker is None or not worker.is_alive()):
            self._append_audio_log_line("DIAG TX worker was not running; restarting")
            self._start_tx_worker()
        try:
            self._tx_queue.put_nowait(pcm_bytes)
            return
        except Full:
            dropped_frames = self._clear_tx_queue()
            try:
                self._tx_queue.put_nowait(pcm_bytes)
            except Full:
                self._append_audio_log_line("TX worker queue remained full while enqueueing a frame")
                return
            now = monotonic()
            if now - self._last_tx_queue_drop_log_at >= 1.0:
                self._last_tx_queue_drop_log_at = now
                self._append_audio_log_line(
                    f"DIAG TX worker queue overflow; dropped {dropped_frames} stale frame(s)"
                )

    def _enqueue_tx_sentinel(self) -> None:
        try:
            self._tx_queue.put_nowait(None)
        except Full:
            try:
                _ = self._tx_queue.get_nowait()
            except Empty:
                pass
            try:
                self._tx_queue.put_nowait(None)
            except Full:
                pass

    def _clear_tx_queue(self) -> int:
        dropped_frames = 0
        while True:
            try:
                self._tx_queue.get_nowait()
            except Empty:
                break
            else:
                dropped_frames += 1
        return dropped_frames

    def _tx_worker_loop(self) -> None:
        while not self._tx_worker_stop.is_set():
            try:
                pcm_bytes = self._tx_queue.get(timeout=0.1)
            except Empty:
                continue
            if pcm_bytes is None:
                continue
            now = monotonic()
            if self._last_tx_send_at > 0.0:
                gap_ms = int((now - self._last_tx_send_at) * 1000)
                if gap_ms >= 120:
                    self._append_audio_log_line(f"DIAG TX send gap {gap_ms}ms")
            self._last_tx_send_at = now
            sent = self.transport.send_pcm_frame_nowait(pcm_bytes)
            if not sent and not self._tx_worker_stop.is_set():
                reason = getattr(self.transport, "last_send_error", "") or "unknown"
                if now - self._last_tx_send_fail_log_at >= 1.0:
                    self._last_tx_send_fail_log_at = now
                    self._append_audio_log_line(f"TX worker failed to send a voice frame ({reason})")

    async def _drain_tx_queue_for_testing(self) -> None:
        while True:
            try:
                pcm_bytes = self._tx_queue.get_nowait()
            except Empty:
                return
            if pcm_bytes is None:
                continue
            await self.transport.send_pcm_frame(pcm_bytes)

    def _schedule_finish_transmit_release(self) -> None:
        loop = self._runtime_loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._finish_transmit_release(), loop)
        except RuntimeError:
            return
