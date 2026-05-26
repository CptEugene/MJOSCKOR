import asyncio

from client.audio import wasapi_playback_host as host_module
from client.audio.wasapi_playback_host import WasapiPlaybackHostProcess
from client.models.audio import AudioDeviceInfo


def test_wasapi_playback_host_builds_args_with_resolved_endpoint(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "MaydayAudioHost.exe"
    executable.write_text("stub", encoding="utf-8")

    process = WasapiPlaybackHostProcess()
    monkeypatch.setattr(
        host_module,
        "resolve_audio_device",
        lambda *_args, **_kwargs: AudioDeviceInfo(
            index=4,
            name="USB DAC",
            max_input_channels=0,
            max_output_channels=2,
            default_sample_rate=48000.0,
            endpoint_id="{0.0.0.00000000}.dac",
        ),
    )
    process.configure(device_index=4, device_name="USB DAC", device_endpoint_id="")

    args = process._command_args(executable)

    assert args[:3] == [str(executable), "--mode", "playback"]
    assert "{0.0.0.00000000}.dac" in args


def test_wasapi_playback_host_updates_ready_state(monkeypatch) -> None:
    process = WasapiPlaybackHostProcess()
    monkeypatch.setattr(
        host_module,
        "resolve_audio_device",
        lambda *_args, **_kwargs: AudioDeviceInfo(
            index=6,
            name="Studio Monitor",
            max_input_channels=0,
            max_output_channels=2,
            default_sample_rate=48000.0,
            endpoint_id="{0.0.0.00000000}.monitor",
        ),
    )
    process.configure(device_index=6, device_name="Studio Monitor", device_endpoint_id="")

    async def exercise() -> None:
        process._ready_future = asyncio.get_running_loop().create_future()
        await process._read_stdout_payload_for_test(
            {
                "event": "ready",
                "device_id": "{0.0.0.00000000}.monitor",
                "device_name": "Studio Monitor",
            }
        )

    asyncio.run(exercise())

    assert process._ready_future is not None and process._ready_future.done()
    assert process.active_device_index == 6
    assert process.active_device_name == "Studio Monitor"
    assert process.active_device_endpoint_id == "{0.0.0.00000000}.monitor"
