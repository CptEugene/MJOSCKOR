from __future__ import annotations

import shutil

from shared.constants.paths import runtime_paths


def ensure_runtime_layout() -> None:
    paths = runtime_paths()
    paths.client_runtime_dir.mkdir(parents=True, exist_ok=True)
    paths.client_logs_dir.mkdir(parents=True, exist_ok=True)
    paths.client_data_dir.mkdir(parents=True, exist_ok=True)
    paths.client_music_dir.mkdir(parents=True, exist_ok=True)
    paths.fonts_dir.mkdir(parents=True, exist_ok=True)
    paths.sound_dir.mkdir(parents=True, exist_ok=True)

    source_icon_ico = paths.root_dir.parent / "icon.ico"
    target_icon_ico = paths.assets_dir / "icon.ico"
    if source_icon_ico.exists() and not target_icon_ico.exists():
        shutil.copy2(source_icon_ico, target_icon_ico)

    source_icon_png = paths.root_dir.parent / "icon.png"
    target_icon_png = paths.assets_dir / "icon.png"
    if source_icon_png.exists() and not target_icon_png.exists():
        shutil.copy2(source_icon_png, target_icon_png)

    source_font = paths.root_dir.parent / "Mabinogi_Classic_TTF.ttf"
    target_font = paths.fonts_dir / "Mabinogi_Classic_TTF.ttf"
    if source_font.exists() and not target_font.exists():
        shutil.copy2(source_font, target_font)

    source_sound_dir = paths.root_dir.parent / "data" / "sound"
    if source_sound_dir.exists():
        for sound_file in list(source_sound_dir.glob("*.wav")) + list(source_sound_dir.glob("*.mp3")):
            target_file = paths.sound_dir / sound_file.name
            if not target_file.exists():
                shutil.copy2(sound_file, target_file)

    source_music_dir = paths.root_dir.parent / "data" / "music"
    if source_music_dir.exists():
        for music_file in source_music_dir.iterdir():
            if not music_file.is_file():
                continue
            target_file = paths.client_music_dir / music_file.name
            if not target_file.exists():
                shutil.copy2(music_file, target_file)
