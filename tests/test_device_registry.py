from client.audio import device_registry as device_registry_module
from client.audio.device_registry import _EndpointInfo, list_audio_devices, resolve_audio_device
from client.models.audio import AudioDeviceInfo


def test_resolve_audio_device_prefers_endpoint_id_then_name(monkeypatch) -> None:
    devices = [
        AudioDeviceInfo(
            index=5,
            name="Broadcast Mic",
            max_input_channels=1,
            max_output_channels=0,
            default_sample_rate=48000.0,
            host_api_name="Windows WASAPI",
            endpoint_id="{0.0.1.00000000}.broadcast",
        ),
        AudioDeviceInfo(
            index=7,
            name="Backup Mic",
            max_input_channels=1,
            max_output_channels=0,
            default_sample_rate=48000.0,
            host_api_name="MME",
            endpoint_id="{0.0.1.00000000}.backup",
        ),
    ]
    monkeypatch.setattr(device_registry_module, "_resolve_devices", lambda direction: devices if direction == "input" else [])
    monkeypatch.setattr(device_registry_module, "_build_sounddevice_candidates", lambda direction: {})

    resolved = resolve_audio_device(
        "input",
        preferred_endpoint_id="{0.0.1.00000000}.broadcast",
        preferred_name="Backup Mic",
        preferred_index=7,
    )

    assert resolved is not None
    assert resolved.index == 5


def test_resolve_audio_device_falls_back_to_sounddevice_name(monkeypatch) -> None:
    fallback = AudioDeviceInfo(
        index=11,
        name="Logitech Headset Mic",
        max_input_channels=1,
        max_output_channels=0,
        default_sample_rate=48000.0,
        host_api_name="Windows DirectSound",
    )
    monkeypatch.setattr(device_registry_module, "_resolve_devices", lambda direction: [])
    monkeypatch.setattr(
        device_registry_module,
        "_build_sounddevice_candidates",
        lambda direction: {"logitech headset mic": fallback} if direction == "input" else {},
    )

    resolved = resolve_audio_device("input", preferred_name="Logitech Headset Mic [Windows WASAPI]")

    assert resolved == fallback


def test_list_audio_devices_keeps_bluetooth_endpoint_when_names_do_not_match(monkeypatch) -> None:
    sony_output = AudioDeviceInfo(
        index=22,
        name="WH-1000XM4 Stereo",
        max_input_channels=0,
        max_output_channels=2,
        default_sample_rate=48000.0,
        host_api_name="Windows WASAPI",
    )
    sony_input = AudioDeviceInfo(
        index=23,
        name="WH-1000XM4 Hands-Free AG Audio",
        max_input_channels=1,
        max_output_channels=0,
        default_sample_rate=16000.0,
        host_api_name="Windows WASAPI",
    )

    def _candidates(direction: str) -> dict[str, AudioDeviceInfo]:
        if direction == "output":
            return {"wh 1000xm4 stereo": sony_output}
        return {"wh 1000xm4 hands free ag audio": sony_input}

    def _endpoints(direction: str) -> list[_EndpointInfo]:
        if direction == "output":
            return [_EndpointInfo("{0.0.0.00000000}.sony-output", "Headphones (WH-1000XM4 Stereo)")]
        return [_EndpointInfo("{0.0.1.00000000}.sony-input", "Headset Microphone (WH-1000XM4 Hands-Free AG Audio)")]

    monkeypatch.setattr(device_registry_module, "_build_sounddevice_candidates", _candidates)
    monkeypatch.setattr(device_registry_module, "_windows_active_endpoints", _endpoints)

    input_devices, output_devices = list_audio_devices()

    assert input_devices[0].name == "Headset Microphone (WH-1000XM4 Hands-Free AG Audio)"
    assert input_devices[0].index == 23
    assert input_devices[0].endpoint_id == "{0.0.1.00000000}.sony-input"
    assert output_devices[0].name == "Headphones (WH-1000XM4 Stereo)"
    assert output_devices[0].index == 22
    assert output_devices[0].endpoint_id == "{0.0.0.00000000}.sony-output"


def test_list_audio_devices_includes_endpoint_only_bluetooth_device(monkeypatch) -> None:
    monkeypatch.setattr(device_registry_module, "_build_sounddevice_candidates", lambda _direction: {})
    monkeypatch.setattr(
        device_registry_module,
        "_windows_active_endpoints",
        lambda direction: [
            _EndpointInfo("{0.0.1.00000000}.sony-input", "Headset Microphone (WH-1000XM4 Hands-Free AG Audio)")
        ]
        if direction == "input"
        else [],
    )

    input_devices, _output_devices = list_audio_devices()

    assert input_devices[0].name == "Headset Microphone (WH-1000XM4 Hands-Free AG Audio)"
    assert input_devices[0].index == -1
    assert input_devices[0].host_api_name == "Windows WASAPI"
    assert input_devices[0].endpoint_id == "{0.0.1.00000000}.sony-input"


def test_list_audio_devices_does_not_append_inactive_sounddevice_candidates(monkeypatch) -> None:
    inactive_candidate = AudioDeviceInfo(
        index=31,
        name="Unused Capture Card",
        max_input_channels=2,
        max_output_channels=0,
        default_sample_rate=48000.0,
        host_api_name="Windows WASAPI",
    )
    monkeypatch.setattr(
        device_registry_module,
        "_build_sounddevice_candidates",
        lambda direction: {"unused capture card": inactive_candidate} if direction == "input" else {},
    )
    monkeypatch.setattr(
        device_registry_module,
        "_windows_active_endpoints",
        lambda direction: [_EndpointInfo("{0.0.1.00000000}.real-mic", "Real Mic")]
        if direction == "input"
        else [],
    )

    input_devices, _output_devices = list_audio_devices()

    assert [device.name for device in input_devices] == ["Real Mic"]
    assert input_devices[0].index == -1
    assert input_devices[0].endpoint_id == "{0.0.1.00000000}.real-mic"
