from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from shared.constants.paths import runtime_paths


class UiSoundPlayer:
    def __init__(self, parent=None) -> None:
        self._audio_output = QAudioOutput(parent)
        self._audio_output.setVolume(0.50)
        self._player = QMediaPlayer(parent)
        self._player.setAudioOutput(self._audio_output)

    def play(self, sound_name: str) -> None:
        path = self._resolve(sound_name)
        if path is None:
            return
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _resolve(self, sound_name: str) -> Path | None:
        sound_dir = runtime_paths().sound_dir
        candidates = [
            sound_dir / sound_name,
            sound_dir / f"{sound_name}.mp3",
            sound_dir / f"{sound_name}.wav",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None
