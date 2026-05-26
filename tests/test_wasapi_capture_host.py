import asyncio
import base64

from client.audio import wasapi_capture_host as host_module
from client.audio.wasapi_capture_host import WasapiCaptureHostProcess
from client.models.audio import AudioDeviceInfo


def test_wasapi_capture_host_builds_args_with_resolved_endpoint(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "MaydayAudioHost.exe"
    executable.write_text("stub", encoding="utf-8")

    process = WasapiCaptureHostProcess()
    monkeypatch.setattr(
        host_module,
        "resolve_audio_device",
        lambda *_args, **_kwargs: AudioDeviceInfo(
            index=3,
            name="Broadcast Mic",
            max_input_channels=1,
            max_output_channels=0,
            default_sample_rate=48000.0,
            endpoint_id="{0.0.1.00000000}.broadcast",
        ),
    )
    process.configure(
        device_index=3,
        device_name="Broadcast Mic",
        device_endpoint_id="",
        frame_handler=None,
        level_handler=None,
    )

    args = process._command_args(executable)

    assert args[:3] == [str(executable), "--mode", "capture"]
    assert "{0.0.1.00000000}.broadcast" in args


def test_wasapi_capture_host_updates_ready_and_dispatches_events(monkeypatch) -> None:
    frames: list[bytes] = []
    levels: list[float] = []

    async def frame_handler(payload: bytes) -> None:
        frames.append(payload)

    process = WasapiCaptureHostProcess()
    monkeypatch.setattr(
        host_module,
        "resolve_audio_device",
        lambda *_args, **_kwargs: AudioDeviceInfo(
            index=8,
            name="USB Mic",
            max_input_channels=1,
            max_output_channels=0,
            default_sample_rate=48000.0,
            endpoint_id="{0.0.1.00000000}.usb",
        ),
    )
    process.configure(
        device_index=8,
        device_name="USB Mic",
        device_endpoint_id="",
        frame_handler=frame_handler,
        level_handler=levels.append,
    )

    async def exercise() -> None:
        process._ready_future = asyncio.get_running_loop().create_future()
        await process._handle_payload(
            {
                "event": "ready",
                "device_id": "{0.0.1.00000000}.usb",
                "device_name": "USB Mic",
            }
        )
        await process._handle_payload({"event": "level", "value": 0.42})
        await process._handle_payload(
            {"event": "frame", "pcm_base64": base64.b64encode(b"pcm").decode("ascii")}
        )

    asyncio.run(exercise())

    assert process._ready_future is not None and process._ready_future.done()
    assert process.active_device_index == 8
    assert process.active_device_name == "USB Mic"
    assert process.active_device_endpoint_id == "{0.0.1.00000000}.usb"
    assert levels == [0.42]
    assert frames == [b"pcm"]
