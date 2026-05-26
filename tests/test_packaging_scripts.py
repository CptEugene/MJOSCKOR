import json
import zipfile


def test_build_client_package(tmp_path, monkeypatch) -> None:
    from shared.constants import paths as paths_module
    from tools import build_client_package as build_client_package_module

    original_runtime_paths = paths_module.runtime_paths

    def fake_runtime_paths():
        paths = original_runtime_paths()
        assets_dir = tmp_path / "assets"
        (assets_dir / "fonts").mkdir(parents=True, exist_ok=True)
        (assets_dir / "sound").mkdir(parents=True, exist_ok=True)
        (assets_dir / "music").mkdir(parents=True, exist_ok=True)
        (assets_dir / "fonts" / "font.ttf").write_text("font", encoding="utf-8")
        (assets_dir / "sound" / "tone.wav").write_text("sound", encoding="utf-8")
        client_runtime = tmp_path / "runtime" / "client"
        (client_runtime / "data").mkdir(parents=True, exist_ok=True)
        (client_runtime / "music").mkdir(parents=True, exist_ok=True)
        (client_runtime / "music" / "briefing.mp3").write_text("music", encoding="utf-8")
        (client_runtime / "data" / "client.toml").write_text("nickname='user'\n", encoding="utf-8")
        return type(paths)(
            root_dir=tmp_path,
            assets_dir=assets_dir,
            icon_file=assets_dir / "icon.png",
            bin_dir=assets_dir / "bin",
            fonts_dir=assets_dir / "fonts",
            sound_dir=assets_dir / "sound",
            music_dir=assets_dir / "music",
            runtime_dir=tmp_path / "runtime",
            client_runtime_dir=client_runtime,
            client_logs_dir=client_runtime / "logs",
            client_data_dir=client_runtime / "data",
            client_music_dir=client_runtime / "music",
            client_config_file=client_runtime / "data" / "client.toml",
            client_package_dir=tmp_path / "dist" / "client",
            server_runtime_dir=tmp_path / "runtime" / "server",
            server_logs_dir=tmp_path / "runtime" / "server" / "logs",
            server_data_dir=tmp_path / "runtime" / "server" / "data",
            server_config_file=tmp_path / "runtime" / "server" / "data" / "server.toml",
            server_package_dir=tmp_path / "dist" / "server",
        )

    monkeypatch.setattr(paths_module, "runtime_paths", fake_runtime_paths)
    monkeypatch.setattr(build_client_package_module, "runtime_paths", fake_runtime_paths)
    package_dir = build_client_package_module.build_client_package()
    assert (package_dir / "data" / "fonts" / "font.ttf").exists()
    assert (package_dir / "data" / "sound" / "tone.wav").exists()
    assert (package_dir / "runtime" / "client" / "music" / "briefing.mp3").exists()
    assert (package_dir / "client.toml").exists()
    assert (package_dir / "manifest.txt").exists()
    version = json.loads((package_dir / "version.json").read_text(encoding="utf-8"))
    assert version["product"] == "MAYDAY"
    assert version["version"]
    assert f"version={version['version']}" in (package_dir / "manifest.txt").read_text(
        encoding="utf-8"
    )
    client_config = (package_dir / "client.toml").read_text(encoding="utf-8")
    assert 'microphone_device_index = -1' in client_config
    assert 'microphone_device_name = ""' in client_config
    assert 'microphone_device_endpoint_id = ""' in client_config
    assert 'speaker_device_index = -1' in client_config
    assert 'speaker_device_name = ""' in client_config
    assert 'speaker_device_endpoint_id = ""' in client_config


def test_build_server_package(tmp_path, monkeypatch) -> None:
    from shared.constants import paths as paths_module
    from tools import build_server_package as build_server_package_module

    original_runtime_paths = paths_module.runtime_paths

    def fake_runtime_paths():
        paths = original_runtime_paths()
        server_runtime = tmp_path / "runtime" / "server"
        (server_runtime / "data").mkdir(parents=True, exist_ok=True)
        (server_runtime / "data" / "server.toml").write_text("password='1234'\n", encoding="utf-8")
        (server_runtime / "data" / "fleet_tree.txt").write_text("{}", encoding="utf-8")
        (server_runtime / "data" / "music").mkdir(parents=True, exist_ok=True)
        (server_runtime / "data" / "music" / "briefing.mp3").write_text("music", encoding="utf-8")
        return type(paths)(
            root_dir=tmp_path,
            assets_dir=tmp_path / "assets",
            icon_file=tmp_path / "assets" / "icon.png",
            bin_dir=tmp_path / "assets" / "bin",
            fonts_dir=tmp_path / "assets" / "fonts",
            sound_dir=tmp_path / "assets" / "sound",
            music_dir=tmp_path / "assets" / "music",
            runtime_dir=tmp_path / "runtime",
            client_runtime_dir=tmp_path / "runtime" / "client",
            client_logs_dir=tmp_path / "runtime" / "client" / "logs",
            client_data_dir=tmp_path / "runtime" / "client" / "data",
            client_music_dir=tmp_path / "runtime" / "client" / "music",
            client_config_file=tmp_path / "runtime" / "client" / "data" / "client.toml",
            client_package_dir=tmp_path / "dist" / "client",
            server_runtime_dir=server_runtime,
            server_logs_dir=server_runtime / "logs",
            server_data_dir=server_runtime / "data",
            server_config_file=server_runtime / "data" / "server.toml",
            server_package_dir=tmp_path / "dist" / "server",
        )

    monkeypatch.setattr(paths_module, "runtime_paths", fake_runtime_paths)
    monkeypatch.setattr(build_server_package_module, "runtime_paths", fake_runtime_paths)
    package_dir = build_server_package_module.build_server_package()
    assert (package_dir / "data" / "server.toml").exists()
    assert (package_dir / "data" / "fleet_tree.txt").exists()
    assert not (package_dir / "data" / "music").exists()
    assert (package_dir / "manifest.txt").exists()


def test_build_update_release_writes_zip_and_manifest(tmp_path, monkeypatch) -> None:
    from shared.constants import paths as paths_module
    from tools import build_update_release as release_module

    original_runtime_paths = paths_module.runtime_paths

    def fake_runtime_paths():
        paths = original_runtime_paths()
        client_package_dir = tmp_path / "dist" / "client"
        client_package_dir.mkdir(parents=True, exist_ok=True)
        (client_package_dir / "Mayday.exe").write_text("exe", encoding="utf-8")
        (client_package_dir / "data").mkdir()
        (client_package_dir / "data" / "icon.png").write_text("icon", encoding="utf-8")
        return type(paths)(
            root_dir=tmp_path,
            assets_dir=tmp_path / "assets",
            icon_file=tmp_path / "assets" / "icon.png",
            bin_dir=tmp_path / "assets" / "bin",
            fonts_dir=tmp_path / "assets" / "fonts",
            sound_dir=tmp_path / "assets" / "sound",
            music_dir=tmp_path / "assets" / "music",
            runtime_dir=tmp_path / "runtime",
            client_runtime_dir=tmp_path / "runtime" / "client",
            client_logs_dir=tmp_path / "runtime" / "client" / "logs",
            client_data_dir=tmp_path / "runtime" / "client" / "data",
            client_music_dir=tmp_path / "runtime" / "client" / "music",
            client_config_file=tmp_path / "runtime" / "client" / "data" / "client.toml",
            client_package_dir=client_package_dir,
            server_runtime_dir=tmp_path / "runtime" / "server",
            server_logs_dir=tmp_path / "runtime" / "server" / "logs",
            server_data_dir=tmp_path / "runtime" / "server" / "data",
            server_config_file=tmp_path / "runtime" / "server" / "data" / "server.toml",
            server_package_dir=tmp_path / "dist" / "server",
        )

    monkeypatch.setattr(paths_module, "runtime_paths", fake_runtime_paths)
    monkeypatch.setattr(release_module, "runtime_paths", fake_runtime_paths)

    archive_path, manifest_path = release_module.build_update_release(
        package_url_base="https://updates.example.test/mayday",
        manifest_url="https://updates.example.test/mayday/mayday_manifest.json",
        notes=["test release"],
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = json.loads((tmp_path / "dist" / "client" / "version.json").read_text(encoding="utf-8"))
    assert archive_path.exists()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "data/" in names
    assert manifest["package_url"].endswith(archive_path.name)
    assert manifest["sha256"]
    assert manifest["notes"] == ["test release"]
    assert version["manifest_url"] == "https://updates.example.test/mayday/mayday_manifest.json"
    assert (tmp_path / "dist" / "cloudview" / "sample_mayday_manifest.json").exists()


def test_build_cloudview_release_writes_exe_and_manifest(tmp_path, monkeypatch) -> None:
    from shared.constants import paths as paths_module
    from tools import build_cloudview_release as cloudview_release_module

    original_runtime_paths = paths_module.runtime_paths

    def fake_runtime_paths():
        paths = original_runtime_paths()
        cloudview_dir = tmp_path / "dist" / "cloudview"
        cloudview_dir.mkdir(parents=True, exist_ok=True)
        (cloudview_dir / "CloudviewCenter.exe").write_text("cloudview exe", encoding="utf-8")
        return type(paths)(
            root_dir=tmp_path,
            assets_dir=tmp_path / "assets",
            icon_file=tmp_path / "assets" / "icon.png",
            bin_dir=tmp_path / "assets" / "bin",
            fonts_dir=tmp_path / "assets" / "fonts",
            sound_dir=tmp_path / "assets" / "sound",
            music_dir=tmp_path / "assets" / "music",
            runtime_dir=tmp_path / "runtime",
            client_runtime_dir=tmp_path / "runtime" / "client",
            client_logs_dir=tmp_path / "runtime" / "client" / "logs",
            client_data_dir=tmp_path / "runtime" / "client" / "data",
            client_music_dir=tmp_path / "runtime" / "client" / "music",
            client_config_file=tmp_path / "runtime" / "client" / "data" / "client.toml",
            client_package_dir=tmp_path / "dist" / "client",
            server_runtime_dir=tmp_path / "runtime" / "server",
            server_logs_dir=tmp_path / "runtime" / "server" / "logs",
            server_data_dir=tmp_path / "runtime" / "server" / "data",
            server_config_file=tmp_path / "runtime" / "server" / "data" / "server.toml",
            server_package_dir=tmp_path / "dist" / "server",
        )

    monkeypatch.setattr(paths_module, "runtime_paths", fake_runtime_paths)
    monkeypatch.setattr(cloudview_release_module, "runtime_paths", fake_runtime_paths)

    package_path, manifest_path = cloudview_release_module.build_cloudview_release(
        package_url_base="https://updates.example.test/cloudview",
        notes=["cloudview release"],
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert package_path.exists()
    assert package_path.name.startswith("CloudviewCenter-")
    assert manifest["product"] == "CLOUDVIEW_CENTER"
    assert manifest["package_url"].endswith(package_path.name)
    assert manifest["sha256"]
    assert manifest["notes"] == ["cloudview release"]


def test_build_mjo_patch_release_writes_live_zip_and_manifest(tmp_path) -> None:
    from tools import build_mjo_patch_release as patch_release_module

    source_zip = tmp_path / "LIVE.zip"
    with zipfile.ZipFile(source_zip, "w") as archive:
        archive.writestr("user.cfg", "g_language = korean_(south_korea)")
        archive.writestr("data/Localization/korean_(south_korea)/global.ini", "hello=안녕")

    package_path, manifest_path = patch_release_module.build_mjo_patch_release(
        source_zip=source_zip,
        output_dir=tmp_path / "release",
        package_url_base="https://updates.example.test/cloudview",
        version="1.0.3",
        notes=["korean patch"],
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert package_path.exists()
    assert package_path.name == "LIVE.zip"
    assert manifest["product"] == "MJO_KOREAN_PATCH"
    assert manifest["latest_version"] == "1.0.3"
    assert manifest["package_url"].endswith("/LIVE.zip")
    assert manifest["sha256"]
    assert manifest["target"] == "StarCitizenRoot"
    assert manifest["notes"] == ["korean patch"]
