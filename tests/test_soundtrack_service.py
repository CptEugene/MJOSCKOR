from client.models.audio import AudioDeviceInfo
from client.services import soundtrack_service as soundtrack_service_module
from client.services.soundtrack_service import SoundtrackService


def test_soundtrack_service_scans_supported_tracks(tmp_path) -> None:
    music_dir = tmp_path / "music"
    logs_dir = tmp_path / "logs"
    music_dir.mkdir(parents=True, exist_ok=True)
    (music_dir / "briefing.mp3").write_text("a", encoding="utf-8")
    (music_dir / "alert.wav").write_text("b", encoding="utf-8")
    (music_dir / "notes.txt").write_text("c", encoding="utf-8")

    service = SoundtrackService(music_dir=music_dir, logs_dir=logs_dir)

    tracks = service.refresh_library()

    assert tracks == ["alert.wav", "briefing.mp3"]


def test_soundtrack_service_resolves_by_name_or_unique_stem(tmp_path) -> None:
    music_dir = tmp_path / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    (music_dir / "Briefing Theme.mp3").write_text("a", encoding="utf-8")

    service = SoundtrackService(music_dir=music_dir, logs_dir=tmp_path / "logs")

    assert service.resolve_track("Briefing Theme.mp3") == music_dir / "Briefing Theme.mp3"
    assert service.resolve_track("briefing theme") == music_dir / "Briefing Theme.mp3"


def test_soundtrack_service_uses_selected_output_device_candidates(tmp_path, monkeypatch) -> None:
    service = SoundtrackService(music_dir=tmp_path / "music", logs_dir=tmp_path / "logs")
    service.configure(7, "USB DAC", "{0.0.0.00000000}.speaker")

    monkeypatch.setattr(
        soundtrack_service_module,
        "resolve_audio_device",
        lambda direction, **_kwargs: AudioDeviceInfo(
            index=7,
            name="USB DAC",
            max_input_channels=0,
            max_output_channels=2,
            default_sample_rate=48000.0,
            endpoint_id="{0.0.0.00000000}.speaker",
        ),
    )
    monkeypatch.setattr(service, "_raw_output_device_name", lambda device_index: "USB DAC [Windows WASAPI]")

    assert service._device_name_candidates() == ["USB DAC", "USB DAC [Windows WASAPI]", None]

