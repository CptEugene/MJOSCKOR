from __future__ import annotations

import json
import shutil
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.constants.app_version import APP_VERSION, build_version_metadata
from shared.constants.channels import DEFAULT_CHANNEL_ASSIGNMENTS, normalize_channel_assignments
from shared.constants.paths import runtime_paths


def _ensure_audio_host_built() -> None:
    project_root = runtime_paths().root_dir
    project_file = project_root / "native" / "MaydayAudioHost" / "MaydayAudioHost.csproj"
    if not project_file.exists():
        return
    try:
        from tools.build_audio_host import build_audio_host
    except Exception:
        return
    build_audio_host()


def _write_sanitized_client_config(source_path: Path, dest_path: Path) -> None:
    try:
        with source_path.open("rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        shutil.copy2(source_path, dest_path)
        return

    def _toml_value(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f'nickname = {_toml_value(str(data.get("nickname", "user")))}',
        f'server_address = {_toml_value(str(data.get("server_address", "127.0.0.1")))}',
        f'server_password = {_toml_value(str(data.get("server_password", "")))}',
        "microphone_device_index = -1",
        'microphone_device_name = ""',
        'microphone_device_endpoint_id = ""',
        "speaker_device_index = -1",
        'speaker_device_name = ""',
        'speaker_device_endpoint_id = ""',
        f'microphone_volume = {int(data.get("microphone_volume", 100))}',
        f'speaker_volume = {int(data.get("speaker_volume", 100))}',
        f'channel_assignments = {_toml_value(normalize_channel_assignments(data.get("channel_assignments", DEFAULT_CHANNEL_ASSIGNMENTS)))}',
        f'channel_receive_volumes = {_toml_value(data.get("channel_receive_volumes", [100, 100, 100, 100]))}',
        f'channel_pan_modes = {_toml_value(data.get("channel_pan_modes", ["both", "both", "both", "both"]))}',
        f'channel_bindings = {_toml_value(data.get("channel_bindings", ["1", "2", "3", "4"]))}',
        f'kneeboard_binding = {_toml_value(str(data.get("kneeboard_binding", "F10")))}',
        f'overlay_chat_size = {_toml_value(str(data.get("overlay_chat_size", "normal")))}',
        "",
    ]
    dest_path.write_text("\n".join(lines), encoding="utf-8")


def build_client_package(package_dir: Path | None = None) -> Path:
    paths = runtime_paths()
    supported_music_extensions = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
    supported_video_extensions = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}
    _ensure_audio_host_built()
    package_dir = package_dir or paths.client_package_dir
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "data" / "bin").mkdir(parents=True, exist_ok=True)
    (package_dir / "data" / "fonts").mkdir(parents=True, exist_ok=True)
    (package_dir / "data" / "sound").mkdir(parents=True, exist_ok=True)
    (package_dir / "data" / "video").mkdir(parents=True, exist_ok=True)
    (package_dir / "runtime" / "client" / "music").mkdir(parents=True, exist_ok=True)
    (package_dir / "runtime" / "client" / "video").mkdir(parents=True, exist_ok=True)

    built_exe = paths.root_dir / "dist" / "Mayday.exe"
    if built_exe.exists():
        shutil.copy2(built_exe, package_dir / "Mayday.exe")

    if paths.icon_file.exists():
        shutil.copy2(paths.icon_file, package_dir / "data" / paths.icon_file.name)
    png_icon = paths.assets_dir / "icon.png"
    ico_icon = paths.assets_dir / "icon.ico"
    if png_icon.exists():
        shutil.copy2(png_icon, package_dir / "data" / "icon.png")
    if ico_icon.exists():
        shutil.copy2(ico_icon, package_dir / "data" / "icon.ico")

    if paths.fonts_dir.exists():
        for item in paths.fonts_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, package_dir / "data" / "fonts" / item.name)
    if paths.sound_dir.exists():
        for item in paths.sound_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, package_dir / "data" / "sound" / item.name)
    asset_video_dir = paths.assets_dir / "video"
    if asset_video_dir.exists():
        for item in asset_video_dir.iterdir():
            if item.is_file() and item.suffix.lower() in supported_video_extensions:
                shutil.copy2(item, package_dir / "data" / "video" / item.name)
    for source_dir in (paths.music_dir, paths.client_music_dir):
        _copy_media_files(
            source_dir,
            package_dir / "runtime" / "client" / "music",
            supported_music_extensions,
        )
    _copy_media_files(
        paths.client_runtime_dir / "video",
        package_dir / "runtime" / "client" / "video",
        supported_video_extensions,
    )
    if paths.bin_dir.exists():
        for item in paths.bin_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, package_dir / "data" / "bin" / item.name)
    if paths.client_config_file.exists():
        _write_sanitized_client_config(paths.client_config_file, package_dir / "client.toml")

    readme = package_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "MAYDAY Python Client Package",
                "",
                "Contents:",
                "- runtime config (optional)",
                "- packaged runtime binaries in data/bin",
                "- packaged assets in data/fonts and data/sound",
                "- local soundtrack tracks in runtime/client/music",
                "- local video overlay files in runtime/client/video",
                "- this scaffold is ready for PyInstaller bundling",
            ]
        ),
        encoding="utf-8",
    )
    manifest = package_dir / "manifest.txt"
    manifest.write_text(
        "\n".join(
            [
                "type=client",
                f"version={APP_VERSION}",
                f"binaries={sum(1 for _ in (package_dir / 'data' / 'bin').glob('*'))}",
                f"fonts={sum(1 for _ in (package_dir / 'data' / 'fonts').glob('*'))}",
                f"sounds={sum(1 for _ in (package_dir / 'data' / 'sound').glob('*'))}",
                f"asset_videos={sum(1 for _ in (package_dir / 'data' / 'video').glob('*'))}",
                f"music={sum(1 for _ in (package_dir / 'runtime' / 'client' / 'music').glob('*'))}",
                f"videos={sum(1 for _ in (package_dir / 'runtime' / 'client' / 'video').glob('*'))}",
                f"exe={'yes' if (package_dir / 'Mayday.exe').exists() else 'no'}",
                f"config={'yes' if (package_dir / 'client.toml').exists() else 'no'}",
            ]
        ),
        encoding="utf-8",
    )
    (package_dir / "version.json").write_text(
        json.dumps(build_version_metadata(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return package_dir


def _copy_media_files(source_dir: Path, dest_dir: Path, supported_extensions: set[str]) -> None:
    if not source_dir.exists():
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        if item.is_file() and item.suffix.lower() in supported_extensions:
            shutil.copy2(item, dest_dir / item.name)


def main() -> int:
    package_dir = build_client_package()
    print(package_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
