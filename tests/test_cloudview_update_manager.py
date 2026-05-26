from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from cloudview.services.update_manager import (
    CloudviewConfig,
    UpdateManager,
    UpdateManifest,
    compare_versions,
    default_cloudview_dir,
    default_cloudview_manifest_url,
    default_install_dir,
    default_mjo_patch_manifest_url,
    default_manifest_url,
)


def test_compare_versions() -> None:
    assert compare_versions("1.0.1", "1.0.2") == -1
    assert compare_versions("1.0.2", "1.0.2") == 0
    assert compare_versions("1.2.0", "1.1.9") == 1
    assert compare_versions("v1.0.10", "1.0.2") == 1


def test_fetch_manifest_from_local_file(tmp_path) -> None:
    package = tmp_path / "client.zip"
    package.write_bytes(b"fake")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "latest_version": "1.0.2",
                "minimum_required_version": "1.0.2",
                "required": True,
                "package_url": str(package),
                "sha256": "",
                "notes": ["test"],
            }
        ),
        encoding="utf-8",
    )

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    manager = UpdateManager(config)
    manifest = manager.fetch_manifest(str(manifest_path))

    assert manifest.latest_version == "1.0.2"
    assert manifest.package_url == str(package)
    assert manager.needs_update("1.0.1", manifest)


def test_default_manifest_url_uses_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOUDVIEW_MAYDAY_MANIFEST_URL", "https://updates.example.test/mayday.json")

    assert (
        default_manifest_url(tmp_path / "cloudview_config.json")
        == "https://updates.example.test/mayday.json"
    )


def test_default_manifest_url_reads_adjacent_source_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLOUDVIEW_MAYDAY_MANIFEST_URL", raising=False)
    (tmp_path / "cloudview_update_source.json").write_text(
        json.dumps({"manifest_url": "https://updates.example.test/mayday.json"}),
        encoding="utf-8",
    )

    config = CloudviewConfig(tmp_path / "cloudview_config.json")

    assert config.manifest_url == "https://updates.example.test/mayday.json"


def test_default_cloudview_manifest_url_reads_adjacent_source_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLOUDVIEW_CENTER_MANIFEST_URL", raising=False)
    (tmp_path / "cloudview_update_source.json").write_text(
        json.dumps(
            {
                "manifest_url": "https://updates.example.test/mayday.json",
                "cloudview_manifest_url": "https://updates.example.test/cloudview.json",
            }
        ),
        encoding="utf-8",
    )

    assert (
        default_cloudview_manifest_url(tmp_path / "cloudview_config.json")
        == "https://updates.example.test/cloudview.json"
    )


def test_default_mjo_patch_manifest_url_reads_adjacent_source_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLOUDVIEW_MJO_PATCH_MANIFEST_URL", raising=False)
    (tmp_path / "cloudview_update_source.json").write_text(
        json.dumps({"mjo_patch_manifest_url": "https://updates.example.test/mjo_patch.json"}),
        encoding="utf-8",
    )

    assert (
        default_mjo_patch_manifest_url(tmp_path / "cloudview_config.json")
        == "https://updates.example.test/mjo_patch.json"
    )


def test_default_cloudview_dir_uses_user_app_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert default_cloudview_dir() == tmp_path / "LocalAppData" / "MJO" / "Cloudview Center"


def test_default_install_dir_uses_cloudview_program_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))

    assert default_install_dir() == tmp_path / "Program Files" / "Cloudview" / "MAYDAY"


def test_install_requires_elevation_for_program_files_target(tmp_path, monkeypatch) -> None:
    program_files = tmp_path / "Program Files"
    monkeypatch.setenv("ProgramFiles", str(program_files))

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.install_dir = program_files / "Cloudview" / "MAYDAY"
    manager = UpdateManager(config)
    manager.is_process_elevated = lambda: False  # type: ignore[method-assign]

    assert manager.install_requires_elevation(config.install_dir)


def test_mayday_install_dir_rejects_dangerous_targets(tmp_path) -> None:
    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    manager = UpdateManager(config)

    with pytest.raises(ValueError):
        manager._validate_mayday_install_dir(tmp_path / "PlainFolder")

    with pytest.raises(ValueError):
        manager._validate_mayday_install_dir(Path(tmp_path.anchor))

    manager._validate_mayday_install_dir(tmp_path / "Cloudview" / "MAYDAY")


def test_install_package_writes_version_and_preserves_config(tmp_path) -> None:
    package = tmp_path / "client.zip"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "Mayday.exe").write_text("new exe", encoding="utf-8")
    with zipfile.ZipFile(package, "w") as archive:
        archive.write(source_dir / "Mayday.exe", "Mayday.exe")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "latest_version": "1.0.2",
                "minimum_required_version": "1.0.2",
                "required": True,
                "package_url": str(package),
                "sha256": "",
                "notes": [],
            }
        ),
        encoding="utf-8",
    )

    install_dir = tmp_path / "MAYDAY"
    install_dir.mkdir()
    (install_dir / "client.toml").write_text("nickname = \"tester\"", encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.manifest_url = str(manifest_path)
    config.install_dir = install_dir
    manager = UpdateManager(config)
    manifest = manager.fetch_manifest(str(manifest_path))
    manager.install_package(package, manifest)

    version = json.loads((install_dir / "version.json").read_text(encoding="utf-8"))
    assert version["version"] == "1.0.2"
    assert version["manifest_url"] == str(manifest_path)
    assert (install_dir / "Mayday.exe").exists()
    assert (install_dir / "client.toml").read_text(encoding="utf-8") == "nickname = \"tester\""
    assert not any(manager.backups_dir.iterdir())


def test_install_package_preserves_runtime_client_data_settings(tmp_path) -> None:
    package = tmp_path / "client.zip"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "Mayday.exe").write_text("new exe", encoding="utf-8")
    with zipfile.ZipFile(package, "w") as archive:
        archive.write(source_dir / "Mayday.exe", "Mayday.exe")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "latest_version": "1.0.2",
                "minimum_required_version": "1.0.2",
                "required": True,
                "package_url": str(package),
                "sha256": "",
                "notes": [],
            }
        ),
        encoding="utf-8",
    )

    install_dir = tmp_path / "MAYDAY"
    data_dir = install_dir / "runtime" / "client" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "client.toml").write_text(
        "\n".join(
            [
                'nickname = "Ace"',
                'server_address = "10.0.0.5"',
                'server_password = "secret"',
                'channel_bindings = ["MOUSE4", "JOY1_BTN1", "CTRL+3", "ALT+4"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "extra_settings.json").write_text('{"keep": true}', encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.manifest_url = str(manifest_path)
    config.install_dir = install_dir
    manager = UpdateManager(config)
    manifest = manager.fetch_manifest(str(manifest_path))
    manager.install_package(package, manifest)

    assert (data_dir / "client.toml").read_text(encoding="utf-8").startswith('nickname = "Ace"')
    assert (data_dir / "extra_settings.json").read_text(encoding="utf-8") == '{"keep": true}'


def test_install_package_preserves_music_and_video_dirs_from_package(tmp_path) -> None:
    package = tmp_path / "client.zip"
    source_dir = tmp_path / "source"
    (source_dir / "runtime" / "client" / "music").mkdir(parents=True)
    (source_dir / "runtime" / "client" / "video").mkdir(parents=True)
    (source_dir / "Mayday.exe").write_text("new exe", encoding="utf-8")
    (source_dir / "runtime" / "client" / "music" / "new.mp3").write_text("new music", encoding="utf-8")
    (source_dir / "runtime" / "client" / "video" / "new.mp4").write_text("new video", encoding="utf-8")
    with zipfile.ZipFile(package, "w") as archive:
        for item in source_dir.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(source_dir).as_posix())

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "latest_version": "1.0.2",
                "minimum_required_version": "1.0.2",
                "required": True,
                "package_url": str(package),
                "sha256": "",
                "notes": [],
            }
        ),
        encoding="utf-8",
    )

    install_dir = tmp_path / "MAYDAY"
    (install_dir / "runtime" / "client" / "music").mkdir(parents=True)
    (install_dir / "runtime" / "client" / "video").mkdir(parents=True)
    (install_dir / "runtime" / "client" / "music" / "old.mp3").write_text("old music", encoding="utf-8")
    (install_dir / "runtime" / "client" / "video" / "old.mp4").write_text("old video", encoding="utf-8")
    (install_dir / "client.toml").write_text("nickname = \"tester\"", encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.manifest_url = str(manifest_path)
    config.install_dir = install_dir
    manager = UpdateManager(config)
    manifest = manager.fetch_manifest(str(manifest_path))
    manager.install_package(package, manifest)

    assert (install_dir / "runtime" / "client" / "music" / "new.mp3").exists()
    assert (install_dir / "runtime" / "client" / "music" / "old.mp3").exists()
    assert (install_dir / "runtime" / "client" / "video" / "new.mp4").exists()
    assert (install_dir / "runtime" / "client" / "video" / "old.mp4").exists()
    assert (install_dir / "client.toml").read_text(encoding="utf-8") == "nickname = \"tester\""


def test_mjo_patch_installs_to_star_citizen_root_and_uninstalls(tmp_path) -> None:
    patch_zip = tmp_path / "LIVE.zip"
    with zipfile.ZipFile(patch_zip, "w") as archive:
        archive.writestr("user.cfg", "g_language = korean_(south_korea)")
        archive.writestr("data/Localization/korean_(south_korea)/global.ini", "hello=안녕")

    starcitizen = tmp_path / "Roberts Space Industries" / "StarCitizen"
    live_dir = starcitizen / "LIVE" / "Bin64"
    live_dir.mkdir(parents=True)
    (live_dir / "StarCitizen.exe").write_text("exe", encoding="utf-8")
    live_root = starcitizen / "LIVE"
    (starcitizen / "user.cfg").write_text("root config must stay", encoding="utf-8")
    (live_root / "user.cfg").write_text("old config", encoding="utf-8")
    existing_global = live_root / "data" / "Localization" / "korean_(south_korea)" / "global.ini"
    existing_global.parent.mkdir(parents=True)
    existing_global.write_text("old global", encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.patch_source = str(patch_zip)
    config.patch_target = str(starcitizen)
    manager = UpdateManager(config)
    manifest = UpdateManifest(
        product="MJO_KOREAN_PATCH",
        latest_version="1.0.2",
        minimum_required_version="1.0.2",
        required=True,
        package_url=str(patch_zip),
        sha256="",
        notes=(),
    )

    install_message = manager.install_mjo_patch_placeholder(manifest_override=manifest)

    assert "설치 완료" in install_message
    assert (starcitizen / "user.cfg").read_text(encoding="utf-8") == "root config must stay"
    assert (live_root / "user.cfg").read_text(encoding="utf-8") == "g_language = korean_(south_korea)"
    assert existing_global.read_text(encoding="utf-8") == "hello=안녕"
    assert manager.mjo_patch_version_path() == (
        live_root / "data" / "Localization" / "korean_(south_korea)" / "mjo_patch_version.json"
    )
    version = json.loads(manager.mjo_patch_version_path().read_text(encoding="utf-8"))
    assert version["version"] == "1.0.2"
    assert not any(item.is_dir() for item in manager.patch_backup_dir.iterdir())

    uninstall_message = manager.uninstall_mjo_patch_placeholder()

    assert "삭제 완료" in uninstall_message
    assert (starcitizen / "user.cfg").read_text(encoding="utf-8") == "root config must stay"
    assert (live_root / "user.cfg").read_text(encoding="utf-8") == "g_language = korean_(south_korea)"
    assert existing_global.read_text(encoding="utf-8") == "hello=안녕"
    assert not manager.mjo_patch_version_path().exists()


def test_mjo_patch_downloads_from_manifest_when_local_zip_is_missing(tmp_path) -> None:
    remote_zip = tmp_path / "remote" / "LIVE.zip"
    remote_zip.parent.mkdir()
    with zipfile.ZipFile(remote_zip, "w") as archive:
        archive.writestr("user.cfg", "g_language = korean_(south_korea)")
        archive.writestr("data/Localization/korean_(south_korea)/global.ini", "hello=안녕")

    manifest_path = tmp_path / "mjo_patch_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MJO_KOREAN_PATCH",
                "latest_version": "1.0.0",
                "minimum_required_version": "1.0.0",
                "required": True,
                "package_url": str(remote_zip),
                "sha256": "",
                "notes": [],
            }
        ),
        encoding="utf-8",
    )

    starcitizen = tmp_path / "Roberts Space Industries" / "StarCitizen"
    (starcitizen / "LIVE" / "Bin64").mkdir(parents=True)
    (starcitizen / "LIVE" / "Bin64" / "StarCitizen.exe").write_text("exe", encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.patch_source = ""
    config.patch_target = str(starcitizen)
    config.mjo_patch_manifest_url = str(manifest_path)
    manager = UpdateManager(config)
    manager.detect_mjo_patch_source = lambda: None  # type: ignore[method-assign]

    manager.install_mjo_patch_placeholder()

    assert (manager.downloads_dir / "LIVE.zip").exists()
    assert (starcitizen / "LIVE" / "user.cfg").read_text(encoding="utf-8") == "g_language = korean_(south_korea)"
    assert (starcitizen / "LIVE" / "data" / "Localization" / "korean_(south_korea)" / "global.ini").exists()
    assert not (starcitizen / "user.cfg").exists()
    assert not (starcitizen / "data").exists()

    manager.uninstall_mjo_patch_placeholder()

    assert not (starcitizen / "LIVE" / "user.cfg").exists()
    assert not (starcitizen / "LIVE" / "data" / "Localization" / "korean_(south_korea)" / "global.ini").exists()


def test_mjo_patch_skips_zip_directory_entries_and_merges_existing_data_dir(tmp_path) -> None:
    patch_zip = tmp_path / "LIVE.zip"
    with zipfile.ZipFile(patch_zip, "w") as archive:
        archive.writestr("data/", "")
        archive.writestr("data/Localization/", "")
        archive.writestr("data/Localization/korean_(south_korea)/", "")
        archive.writestr("data/Localization/korean_(south_korea)/global.ini", "hello=안녕")
        archive.writestr("user.cfg", "g_language = korean_(south_korea)")

    starcitizen = tmp_path / "Roberts Space Industries" / "StarCitizen"
    (starcitizen / "LIVE" / "Bin64").mkdir(parents=True)
    (starcitizen / "LIVE" / "Bin64" / "StarCitizen.exe").write_text("exe", encoding="utf-8")
    (starcitizen / "LIVE" / "data" / "existing").mkdir(parents=True)
    (starcitizen / "LIVE" / "data" / "existing" / "keep.txt").write_text("keep", encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.patch_source = str(patch_zip)
    config.patch_target = str(starcitizen)
    manager = UpdateManager(config)

    manager.install_mjo_patch_placeholder()

    assert (starcitizen / "LIVE" / "data" / "existing" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (starcitizen / "LIVE" / "data" / "Localization" / "korean_(south_korea)" / "global.ini").exists()
    assert not (starcitizen / "data").exists()


def test_mjo_patch_replaces_broken_data_file_with_directory(tmp_path) -> None:
    patch_zip = tmp_path / "LIVE.zip"
    with zipfile.ZipFile(patch_zip, "w") as archive:
        archive.writestr("data/", "")
        archive.writestr("data/Localization/korean_(south_korea)/global.ini", "hello=안녕")
        archive.writestr("user.cfg", "g_language = korean_(south_korea)")

    starcitizen = tmp_path / "Roberts Space Industries" / "StarCitizen"
    (starcitizen / "LIVE" / "Bin64").mkdir(parents=True)
    (starcitizen / "LIVE" / "Bin64" / "StarCitizen.exe").write_text("exe", encoding="utf-8")
    (starcitizen / "LIVE" / "data").write_text("broken previous install", encoding="utf-8")

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.patch_source = str(patch_zip)
    config.patch_target = str(starcitizen)
    manager = UpdateManager(config)

    manager.install_mjo_patch_placeholder()

    assert (starcitizen / "LIVE" / "data").is_dir()
    assert (starcitizen / "LIVE" / "data" / "Localization" / "korean_(south_korea)" / "global.ini").exists()
    assert not (starcitizen / "data").exists()


def test_mjo_patch_uses_selected_channel_dir_without_crashing_on_startup(tmp_path) -> None:
    patch_zip = tmp_path / "LIVE.zip"
    with zipfile.ZipFile(patch_zip, "w") as archive:
        archive.writestr("data/Localization/korean_(south_korea)/global.ini", "hello=안녕")
        archive.writestr("user.cfg", "g_language = korean_(south_korea)")

    starcitizen = tmp_path / "Roberts Space Industries" / "StarCitizen"
    hotfix = starcitizen / "HOTFIX"
    hotfix.mkdir(parents=True)

    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.patch_source = str(patch_zip)
    config.patch_target = str(hotfix)
    manager = UpdateManager(config)

    assert manager.read_installed_mjo_patch_version() is None

    manager.install_mjo_patch_placeholder()

    assert (hotfix / "user.cfg").read_text(encoding="utf-8") == "g_language = korean_(south_korea)"
    assert (hotfix / "data" / "Localization" / "korean_(south_korea)" / "global.ini").exists()
    assert not (starcitizen / "user.cfg").exists()
    assert not (starcitizen / "data").exists()


def test_mjo_patch_bad_saved_target_does_not_crash_state_refresh(tmp_path) -> None:
    config = CloudviewConfig(tmp_path / "cloudview_config.json")
    config.patch_target = str(tmp_path / "missing" / "HOTFIX")
    manager = UpdateManager(config)

    assert manager.read_installed_mjo_patch_version() is None
    assert not manager.patch_requires_elevation()
