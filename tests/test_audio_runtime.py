import asyncio

import pytest

from client.audio.effects import rx_start_tone, tx_start_tone
from client.audio.talker_buffer import TalkerAudioBuffer
from client.models.audio import VoiceFrame
from client.services.audio_runtime import AudioRuntime


class _DummyTransport:
    def __init__(self) -> None:
        self.channel_tag = "general"
        self.sent: list[bytes] = []

    async def send_pcm_frame(self, pcm_bytes: bytes) -> None:
        self.sent.append(pcm_bytes)


def test_audio_runtime_flushes_preroll_on_ptt_start() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()
        runtime.transport = _DummyTransport()  # type: ignore[assignment]
        runtime.set_slot_joined(True)
        frame = (1000).to_bytes(2, "little", signed=True) * 960

        await runtime._send_processed_frame(frame)
        await runtime._send_processed_frame(frame)
        assert len(runtime.transport.sent) == 0

        await runtime.start_transmit()
        await runtime._send_processed_frame(frame)

        assert len(runtime.transport.sent) == 3
        assert runtime._flush_tx_preroll is False
        assert runtime.state.tx_preroll_frames_sent == 2

    asyncio.run(_run())


def test_audio_runtime_sends_release_tail_before_stop() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()
        runtime.transport = _DummyTransport()  # type: ignore[assignment]
        runtime.set_slot_joined(True)
        frame = (1000).to_bytes(2, "little", signed=True) * 960

        await runtime.start_transmit()
        await runtime._send_processed_frame(frame)
        assert runtime.state.transmitting is True

        await runtime.stop_transmit()
        assert runtime.state.transmitting is True

        for _ in range(4):
            await runtime._send_processed_frame(frame)
            assert runtime.state.transmitting is True

        await runtime._send_processed_frame(frame)
        assert runtime.state.transmitting is False
        assert runtime.state.tx_release_frames_sent == 5
        assert len(runtime.transport.sent) == 6

    asyncio.run(_run())


def test_audio_runtime_stop_transmit_recovers_when_no_frames_were_captured() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()
        runtime.transport = _DummyTransport()  # type: ignore[assignment]
        runtime.set_slot_joined(True)

        await runtime.start_transmit()
        assert runtime.state.transmitting is True

        await runtime.stop_transmit()

        assert runtime.state.transmitting is False
        assert runtime._tx_ptt_pressed is False

        await runtime.start_transmit()
        assert runtime.state.transmitting is True

    asyncio.run(_run())


def test_audio_runtime_conceals_single_gap_and_tracks_late_drop() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()
        frame = (1000).to_bytes(2, "little", signed=True) * 960

        await runtime._enqueue_voice(frame, "general", session_id=7, packet_number=10)
        await runtime._enqueue_voice(frame, "general", session_id=7, packet_number=11)
        await runtime._enqueue_voice(frame, "general", session_id=7, packet_number=12)
        await runtime._enqueue_voice(frame, "general", session_id=7, packet_number=13)
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()

        await runtime._enqueue_voice(frame, "general", session_id=7, packet_number=15)
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()
        assert runtime.state.rx_packets_skipped == 0

        await runtime._enqueue_voice(frame, "general", session_id=7, packet_number=10)
        assert runtime.state.rx_packets_late_dropped == 1

    asyncio.run(_run())


def test_audio_runtime_tracks_rx_skip_for_larger_gap() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()
        frame = (1000).to_bytes(2, "little", signed=True) * 960

        await runtime._enqueue_voice(frame, "general", session_id=9, packet_number=20)
        await runtime._enqueue_voice(frame, "general", session_id=9, packet_number=21)
        await runtime._enqueue_voice(frame, "general", session_id=9, packet_number=22)
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()

        await runtime._enqueue_voice(frame, "general", session_id=9, packet_number=31)
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()
        _ = runtime._drain_ready_playout_frames()
        await runtime._enqueue_voice(frame, "general", session_id=9, packet_number=32)
        await runtime._enqueue_voice(frame, "general", session_id=9, packet_number=33)
        _ = runtime._drain_ready_playout_frames()

        assert runtime.state.rx_packets_skipped == 8

    asyncio.run(_run())


def test_audio_runtime_mix_pcm16_streams_matches_srs_style_sum() -> None:
    runtime = AudioRuntime()
    frame_a = (1000).to_bytes(2, "little", signed=True) * 8
    frame_b = (2000).to_bytes(2, "little", signed=True) * 8

    mixed = runtime._mix_pcm16_streams([frame_a, frame_b])

    assert mixed == (3000).to_bytes(2, "little", signed=True) * 8


def test_audio_runtime_microphone_slider_gain_curve_is_dramatic() -> None:
    runtime = AudioRuntime()

    assert runtime._slider_gain(100) == 1.0
    assert runtime._slider_gain(50) == 0.25
    assert runtime._slider_gain(150) == 2.5
    assert runtime._slider_gain(200) == 4.0


def test_audio_runtime_receive_slider_gain_curve_is_more_aggressive() -> None:
    runtime = AudioRuntime()

    assert runtime._receive_slider_gain(100) == 1.0
    assert runtime._receive_slider_gain(50) == 0.125
    assert runtime._receive_slider_gain(150) == 4.5
    assert runtime._receive_slider_gain(200) == 8.0


def test_audio_runtime_receive_gain_combines_channel_and_master_volume() -> None:
    runtime = AudioRuntime()
    runtime.settings.speaker_volume_percent = 50
    runtime.settings.channel_receive_volumes = [50, 100, 100, 100]

    assert runtime._receive_gain("squad") == pytest.approx(0.125 * 0.125 * 0.42)


def test_audio_runtime_output_limiter_reduces_hot_mix_peak() -> None:
    runtime = AudioRuntime()

    limited = runtime._limit_float_stream([1.45, -1.45, 0.6, -0.6])

    assert max(abs(sample) for sample in limited) <= 1.0
    assert abs(limited[0]) < 0.95


def test_audio_runtime_output_limiter_recovers_after_reset() -> None:
    runtime = AudioRuntime()

    _ = runtime._limit_float_stream([1.35, -1.35, 1.1, -1.1])
    runtime._output_limiter.reset()
    recovered = runtime._limit_float_stream([0.25, -0.25, 0.15, -0.15])

    assert recovered == [0.25, -0.25, 0.15, -0.15]


def test_audio_runtime_meter_toggle_controls_level_handler() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()

        assert runtime.capture._level_handler is None

        await runtime.start_level_meter()
        assert runtime.meter_enabled() is True
        assert runtime.capture._level_handler is not None

        runtime._update_microphone_level(0.42)
        assert runtime.state.microphone_level == 0.42

        await runtime.stop_level_meter()
        assert runtime.meter_enabled() is False
        assert runtime.capture._level_handler is None

        runtime._update_microphone_level(0.91)
        assert runtime.state.microphone_level == 0.0

    asyncio.run(_run())


def test_audio_runtime_resets_talker_buffer_on_new_transmission_without_tx_effect() -> None:
    async def _run() -> None:
        runtime = AudioRuntime()
        runtime._talker_buffers[7] = TalkerAudioBuffer()
        runtime.set_slot_joined(True)

        old_buffer = runtime._talker_buffers[7]
        frame = VoiceFrame(
            session_id=7,
            channel_tag="general",
            codec="opus",
            pcm_bytes=(1000).to_bytes(2, "little", signed=True) * 1920,
            packet_number=50,
            new_transmission=True,
        )

        await runtime._handle_received_frame(frame)

        assert runtime._talker_buffers[7] is not old_buffer
        assert runtime._talker_channels[7] == "general"

    asyncio.run(_run())


def test_radio_tones_are_general_only() -> None:
    assert tx_start_tone("squad") == b""
    assert rx_start_tone("hq") != b""


def test_audio_runtime_uses_native_engine_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MAYDAY_NATIVE_AUDIO_ENGINE", raising=False)

    runtime = AudioRuntime()

    assert runtime._native_engine_enabled is True


def test_audio_runtime_allows_native_engine_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("MAYDAY_NATIVE_AUDIO_ENGINE", "0")

    runtime = AudioRuntime()

    assert runtime._native_engine_enabled is False


def test_audio_runtime_restart_live_streams_restarts_after_stopping_native_engine() -> None:
    class _Engine:
        def __init__(self) -> None:
            self.running = True
            self.stop_count = 0

        async def stop(self) -> None:
            self.stop_count += 1
            self.running = False

    async def _run() -> None:
        runtime = AudioRuntime()
        engine = _Engine()
        runtime.engine = engine  # type: ignore[assignment]
        runtime._started = True
        start_called = False

        async def _start() -> None:
            nonlocal start_called
            start_called = True
            assert runtime._started is False
            runtime._started = True

        runtime.start = _start  # type: ignore[method-assign]

        await runtime.restart_live_streams()

        assert engine.stop_count == 1
        assert start_called is True

    asyncio.run(_run())
