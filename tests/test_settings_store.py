from client.services.settings_store import SettingsStore
from shared.models.app_settings import AppSettings


def test_settings_store_roundtrip(tmp_path, monkeypatch) -> None:
    from shared.constants import paths as paths_module
    from client.services import settings_store as settings_store_module

    original_runtime_paths = paths_module.runtime_paths

    def fake_runtime_paths():
        paths = original_runtime_paths()
        return type(paths)(
            root_dir=paths.root_dir,
            assets_dir=paths.assets_dir,
            icon_file=paths.icon_file,
            bin_dir=paths.bin_dir,
            fonts_dir=paths.fonts_dir,
            sound_dir=paths.sound_dir,
            music_dir=paths.music_dir,
            runtime_dir=tmp_path,
            client_runtime_dir=tmp_path / "client",
            client_logs_dir=tmp_path / "client" / "logs",
            client_data_dir=tmp_path / "client" / "data",
            client_music_dir=tmp_path / "client" / "music",
            client_config_file=tmp_path / "client" / "data" / "client.toml",
            client_package_dir=tmp_path / "dist" / "client",
            server_runtime_dir=tmp_path / "server",
            server_logs_dir=tmp_path / "server" / "logs",
            server_data_dir=tmp_path / "server" / "data",
            server_config_file=tmp_path / "server" / "data" / "server.toml",
            server_package_dir=tmp_path / "dist" / "server",
        )

    monkeypatch.setattr(paths_module, "runtime_paths", fake_runtime_paths)
    monkeypatch.setattr(settings_store_module, "runtime_paths", fake_runtime_paths)
    store = SettingsStore()
    source = AppSettings(
        nickname="pilot",
        server_address="10.0.0.4",
        server_password="1234",
        microphone_device_index=2,
        microphone_device_name="USB Mic",
        microphone_device_endpoint_id="{0.0.1.00000000}.mic",
        speaker_device_index=3,
        speaker_device_name="USB DAC",
        speaker_device_endpoint_id="{0.0.0.00000000}.speaker",
        microphone_volume=135,
        channel_assignments=[4, 3, 2, 1],
        channel_receive_volumes=[100, 90, 80, 70],
        channel_bindings=["CTRL+1", "MOUSE4", "JOY1_BTN1", "ALT+4"],
        kneeboard_binding="SHIFT+K",
        overlay_chat_size="large",
    )
    store.save(source)
    loaded = store.load()
    assert loaded.nickname == "pilot"
    assert loaded.server_address == "10.0.0.4"
    assert loaded.microphone_device_name == "USB Mic"
    assert loaded.microphone_device_endpoint_id == "{0.0.1.00000000}.mic"
    assert loaded.speaker_device_name == "USB DAC"
    assert loaded.speaker_device_endpoint_id == "{0.0.0.00000000}.speaker"
    assert loaded.channel_assignments == [4, 3, 2, 1]
    assert loaded.channel_receive_volumes == [100, 90, 80, 70]
    assert loaded.channel_bindings == ["CTRL+1", "MOUSE4", "JOY1_BTN1", "ALT+4"]
    assert loaded.kneeboard_binding == "SHIFT+K"
    assert loaded.overlay_chat_size == "large"
