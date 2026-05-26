from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sys


@dataclass(frozen=True)
class RuntimePaths:
    root_dir: Path
    assets_dir: Path
    icon_file: Path
    bin_dir: Path
    fonts_dir: Path
    sound_dir: Path
    music_dir: Path
    runtime_dir: Path
    client_runtime_dir: Path
    client_logs_dir: Path
    client_data_dir: Path
    client_music_dir: Path
    client_config_file: Path
    client_package_dir: Path
    server_runtime_dir: Path
    server_logs_dir: Path
    server_data_dir: Path
    server_config_file: Path
    server_package_dir: Path


@lru_cache(maxsize=1)
def runtime_paths() -> RuntimePaths:
    if getattr(sys, "frozen", False):
        root_dir = Path(sys.executable).resolve().parent
        bundle_dir = Path(getattr(sys, "_MEIPASS", root_dir))
        if (root_dir / "data").exists():
            assets_dir = root_dir / "data"
            runtime_dir = root_dir / "runtime"
            client_config_file = root_dir / "client.toml"
            server_data_dir = root_dir / "data"
            server_config_file = server_data_dir / "server.toml"
        else:
            bundled_assets_dir = bundle_dir / "assets"
            assets_dir = bundled_assets_dir if bundled_assets_dir.exists() else root_dir / "assets"
            runtime_dir = root_dir / "runtime"
            client_config_file = runtime_dir / "client" / "data" / "client.toml"
            server_data_dir = runtime_dir / "server" / "data"
            server_config_file = server_data_dir / "server.toml"
    else:
        root_dir = Path(__file__).resolve().parents[2]
        assets_dir = root_dir / "assets"
        runtime_dir = root_dir / "runtime"
        client_config_file = runtime_dir / "client" / "data" / "client.toml"
        server_data_dir = runtime_dir / "server" / "data"
        server_config_file = server_data_dir / "server.toml"

    client_runtime_dir = runtime_dir / "client"
    server_runtime_dir = runtime_dir / "server"

    return RuntimePaths(
        root_dir=root_dir,
        assets_dir=assets_dir,
        icon_file=(assets_dir / "icon.ico") if (assets_dir / "icon.ico").exists() else (assets_dir / "icon.png"),
        bin_dir=assets_dir / "bin",
        fonts_dir=assets_dir / "fonts",
        sound_dir=assets_dir / "sound",
        music_dir=assets_dir / "music",
        runtime_dir=runtime_dir,
        client_runtime_dir=client_runtime_dir,
        client_logs_dir=client_runtime_dir / "logs",
        client_data_dir=client_runtime_dir / "data",
        client_music_dir=client_runtime_dir / "music",
        client_config_file=client_config_file,
        client_package_dir=root_dir / "dist" / "client",
        server_runtime_dir=server_runtime_dir,
        server_logs_dir=server_runtime_dir / "logs",
        server_data_dir=server_data_dir,
        server_config_file=server_config_file,
        server_package_dir=root_dir / "dist" / "server",
    )
