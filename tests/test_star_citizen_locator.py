from __future__ import annotations

import json

from cloudview.services.star_citizen_locator import (
    detect_star_citizen_install,
    resolve_star_citizen_channel_dir,
    resolve_star_citizen_root_dir,
)


def test_resolve_star_citizen_channel_dir_from_live_folder(tmp_path) -> None:
    live_dir = tmp_path / "Roberts Space Industries" / "StarCitizen" / "LIVE"
    (live_dir / "Bin64").mkdir(parents=True)
    (live_dir / "Bin64" / "StarCitizen.exe").write_text("exe", encoding="utf-8")

    assert resolve_star_citizen_channel_dir(live_dir) == live_dir
    assert resolve_star_citizen_root_dir(live_dir) == live_dir.parent


def test_resolve_star_citizen_channel_dir_from_starcitizen_root(tmp_path) -> None:
    root = tmp_path / "Roberts Space Industries" / "StarCitizen"
    live_dir = root / "LIVE"
    (live_dir / "Bin64").mkdir(parents=True)
    (live_dir / "Bin64" / "StarCitizen.exe").write_text("exe", encoding="utf-8")

    assert resolve_star_citizen_channel_dir(root) == live_dir


def test_detect_star_citizen_install_from_rsi_launcher_config(tmp_path, monkeypatch) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    launcher_dir = appdata / "rsilauncher"
    launcher_dir.mkdir(parents=True)

    game_root = tmp_path / "Games" / "Roberts Space Industries" / "StarCitizen"
    live_dir = game_root / "LIVE"
    (live_dir / "Bin64").mkdir(parents=True)
    (live_dir / "Bin64" / "StarCitizen.exe").write_text("exe", encoding="utf-8")
    (launcher_dir / "settings.json").write_text(
        json.dumps({"libraryFolder": str(tmp_path / "Games" / "Roberts Space Industries")}),
        encoding="utf-8",
    )

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramW6432", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Program Files (x86)"))

    assert detect_star_citizen_install() == game_root
