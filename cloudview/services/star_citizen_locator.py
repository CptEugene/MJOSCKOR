from __future__ import annotations

import json
import os
import re
from pathlib import Path


STAR_CITIZEN_CHANNELS = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")


def detect_star_citizen_install() -> Path | None:
    """Return the Star Citizen root folder, for example .../Roberts Space Industries/StarCitizen."""
    for candidate in star_citizen_path_candidates():
        root_dir = resolve_star_citizen_root_dir(candidate)
        if root_dir is not None:
            return root_dir
    return None


def star_citizen_path_candidates() -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(_launcher_config_candidates())
    candidates.extend(_common_install_candidates())
    return _unique_existing_or_possible(candidates)


def resolve_star_citizen_root_dir(path: Path) -> Path | None:
    path = path.expanduser()
    if _is_channel_dir(path):
        return path.parent
    if path.name.upper() in STAR_CITIZEN_CHANNELS and path.exists():
        return path.parent

    star_citizen_dir = path / "StarCitizen"
    if star_citizen_dir.exists():
        path = star_citizen_dir

    for channel in STAR_CITIZEN_CHANNELS:
        channel_dir = path / channel
        if _is_channel_dir(channel_dir):
            return path

    if path.name.lower() == "starcitizen":
        for channel in STAR_CITIZEN_CHANNELS:
            channel_dir = path / channel
            if channel_dir.exists():
                return path
    return None


def resolve_star_citizen_channel_dir(path: Path) -> Path | None:
    path = path.expanduser()
    if path.name.upper() in STAR_CITIZEN_CHANNELS and path.exists():
        return path
    root_dir = resolve_star_citizen_root_dir(path)
    if root_dir is None:
        return None
    for channel in STAR_CITIZEN_CHANNELS:
        channel_dir = root_dir / channel
        if _is_channel_dir(channel_dir):
            return channel_dir
    return None


def _is_channel_dir(path: Path) -> bool:
    return (path / "Bin64" / "StarCitizen.exe").exists()


def _launcher_config_candidates() -> list[Path]:
    candidates: list[Path] = []
    app_data = os.environ.get("APPDATA")
    local_app_data = os.environ.get("LOCALAPPDATA")
    roots = [
        Path(app_data) / "rsilauncher" if app_data else None,
        Path(local_app_data) / "rsilauncher" if local_app_data else None,
    ]
    for root in roots:
        if root is None or not root.exists():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in {".json", ".cfg", ".ini", ".log"}:
                continue
            candidates.extend(_paths_from_launcher_file(file_path))
    return candidates


def _paths_from_launcher_file(file_path: Path) -> list[Path]:
    try:
        text = file_path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return []

    candidates: list[Path] = []
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if data is not None:
        candidates.extend(_paths_from_json_value(data))

    # RSI launcher config/log files commonly contain Windows paths as plain strings.
    pattern = re.compile(r"[A-Za-z]:[\\/][^\"'\r\n<>|]+")
    for match in pattern.findall(text):
        cleaned = match.strip().rstrip(" ,;")
        if "StarCitizen" in cleaned or "Roberts Space Industries" in cleaned:
            candidates.append(Path(cleaned))
    return candidates


def _paths_from_json_value(value: object) -> list[Path]:
    candidates: list[Path] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("library", "install", "game", "path", "folder")):
                candidates.extend(_paths_from_json_value(item))
            else:
                candidates.extend(_paths_from_json_value(item))
    elif isinstance(value, list):
        for item in value:
            candidates.extend(_paths_from_json_value(item))
    elif isinstance(value, str):
        if "StarCitizen" in value or "Roberts Space Industries" in value:
            candidates.append(Path(value))
    return candidates


def _common_install_candidates() -> list[Path]:
    bases: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(env_name)
        if value:
            bases.append(Path(value))
    system_drive = os.environ.get("SystemDrive", "C:")
    bases.extend(Path(f"{letter}:\\") for letter in "CDEFGHI" if Path(f"{letter}:\\").exists())
    bases.append(Path(system_drive) / "Games")
    bases.append(Path(system_drive) / "RSI")

    candidates: list[Path] = []
    for base in bases:
        candidates.extend(
            [
                base / "Roberts Space Industries" / "StarCitizen",
                base / "StarCitizen",
                base / "Games" / "StarCitizen",
                base / "RSI" / "StarCitizen",
            ]
        )
    return candidates


def _unique_existing_or_possible(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path.expanduser()).lower().rstrip("\\/")
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(path.expanduser())
    return unique
