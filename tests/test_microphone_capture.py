from client.audio.microphone_capture import MicrophoneCaptureService


class _FakeSoundDevice:
    def __init__(self) -> None:
        self._devices = [
            {
                "name": "Logitech G Pro X [Windows WASAPI]",
                "max_input_channels": 1,
                "hostapi": 0,
                "default_samplerate": 48_000.0,
            },
            {
                "name": "Logitech G Pro X [MME]",
                "max_input_channels": 1,
                "hostapi": 1,
                "default_samplerate": 48_000.0,
            },
            {
                "name": "Logitech G Pro X [Windows DirectSound]",
                "max_input_channels": 1,
                "hostapi": 2,
                "default_samplerate": 48_000.0,
            },
            {
                "name": "Different Mic [MME]",
                "max_input_channels": 1,
                "hostapi": 1,
                "default_samplerate": 48_000.0,
            },
        ]
        self._host_apis = [
            {"name": "Windows WASAPI"},
            {"name": "MME"},
            {"name": "Windows DirectSound"},
        ]

    def query_devices(self, index=None, kind=None):  # noqa: ANN001
        if kind == "input":
            return self._devices[0]
        if index is None:
            return self._devices
        return self._devices[index]

    def query_hostapis(self):
        return self._host_apis


def test_microphone_capture_prefers_compatibility_host_order_for_same_endpoint() -> None:
    service = MicrophoneCaptureService()
    service.device_index = 0

    candidate_indexes = service._candidate_input_indexes(_FakeSoundDevice())

    assert candidate_indexes == [0, 2, 1]


def test_microphone_capture_candidate_sample_rates_try_safe_values_before_device_default() -> None:
    service = MicrophoneCaptureService()

    candidate_rates = service._candidate_sample_rates({"default_samplerate": 192_000.0})

    assert candidate_rates[:4] == [48_000, 44_100, 32_000, 192_000]
    assert candidate_rates[-1] == 192_000


def test_microphone_capture_plain_stream_attempt_is_used_for_non_wasapi_hosts() -> None:
    service = MicrophoneCaptureService()

    attempts = service._stream_open_attempts(_FakeSoundDevice(), "MME")

    assert attempts == [
        {
            "label": "plain",
            "extra_settings": None,
            "never_drop_input": False,
        }
    ]


def test_microphone_capture_wasapi_attempts_fall_back_to_plain_mode() -> None:
    service = MicrophoneCaptureService()

    attempts = service._stream_open_attempts(_FakeSoundDevice(), "Windows WASAPI")

    assert [attempt["label"] for attempt in attempts] == ["plain"]
    assert all(attempt["never_drop_input"] is False for attempt in attempts)
