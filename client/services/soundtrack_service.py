from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from client.audio.device_registry import resolve_audio_device
from shared.constants.paths import runtime_paths

SUPPORTED_SOUNDTRACK_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac"}


@dataclass(slots=True)
class SoundtrackState:
    available_tracks: list[str] = field(default_factory=list)
    current_track_id: str = ""
    playing: bool = False
    volume_percent: int = 10
    last_error: str = ""


class SoundtrackService:
    def __init__(self, music_dir: Path | None = None, logs_dir: Path | None = None) -> None:
        paths = runtime_paths()
        self.music_dir = music_dir or paths.client_music_dir
        self.logs_dir = logs_dir or paths.client_logs_dir
        self.state = SoundtrackState()
        self.device_index: int | None = None
        self.device_name = ""
        self.device_endpoint_id = ""
        self._pygame = None
        self._active_device_name: str | None = None
        self._prepared_track_id = ""

    def configure(
        self,
        device_index: int | None,
        device_name: str = "",
        device_endpoint_id: str = "",
    ) -> None:
        normalized_name = device_name.strip()
        normalized_endpoint_id = device_endpoint_id.strip()
        if (
            self.device_index == device_index
            and self.device_name == normalized_name
            and self.device_endpoint_id == normalized_endpoint_id
        ):
            return
        self.device_index = device_index
        self.device_name = normalized_name
        self.device_endpoint_id = normalized_endpoint_id
        self._active_device_name = None
        pygame = self._pygame
        if pygame is None or not pygame.mixer.get_init():
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        self.state.playing = False
        self.state.current_track_id = ""
        self._prepared_track_id = ""

    def refresh_library(self) -> list[str]:
        self.music_dir.mkdir(parents=True, exist_ok=True)
        tracks = sorted(
            [
                item.name
                for item in self._track_paths()
            ],
            key=str.lower,
        )
        self.state.available_tracks = tracks
        return list(tracks)

    def play(self, track_id: str, volume_percent: int = 10, fade_ms: int = 1200) -> bool:
        normalized_track_id = track_id.strip()
        if self._prepared_track_id != normalized_track_id and not self.prepare(track_id, volume_percent=volume_percent):
            return False
        return self.play_prepared(volume_percent=volume_percent, fade_ms=fade_ms)

    def prepare(self, track_id: str, volume_percent: int = 10) -> bool:
        track_path = self.resolve_track(track_id)
        if track_path is None:
            self._set_error(f"track not found: {track_id}")
            return False
        try:
            pygame = self._ensure_pygame()
            if pygame is None:
                self._set_error("pygame is not available")
                return False
            self._ensure_mixer_ready(pygame)
            normalized_volume = max(0, min(200, int(volume_percent)))
            pygame.mixer.music.load(str(track_path))
            pygame.mixer.music.set_volume(normalized_volume / 100.0)
            self._prepared_track_id = track_path.name
            self.state.current_track_id = track_path.name
            self.state.volume_percent = normalized_volume
            self.state.last_error = ""
            self._log(f"PREPARE {track_path.name} volume={normalized_volume}")
            return True
        except Exception as exc:
            self._set_error(str(exc))
            self._prepared_track_id = ""
            return False

    def play_prepared(self, volume_percent: int = 10, fade_ms: int = 1200) -> bool:
        if not self._prepared_track_id:
            self._set_error("no prepared soundtrack")
            return False
        try:
            pygame = self._ensure_pygame()
            if pygame is None:
                self._set_error("pygame is not available")
                return False
            normalized_volume = max(0, min(200, int(volume_percent)))
            normalized_fade = max(0, int(fade_ms))
            pygame.mixer.music.set_volume(normalized_volume / 100.0)
            pygame.mixer.music.play(fade_ms=normalized_fade)
            self.state.current_track_id = self._prepared_track_id
            self.state.playing = True
            self.state.volume_percent = normalized_volume
            self.state.last_error = ""
            self._log(f"PLAY {self._prepared_track_id} volume={normalized_volume} fade_ms={normalized_fade}")
            return True
        except Exception as exc:
            self._set_error(str(exc))
            return False

    def stop(self, fade_ms: int = 600) -> None:
        pygame = self._pygame
        if pygame is None:
            self.state.playing = False
            self.state.current_track_id = ""
            return
        try:
            if pygame.mixer.get_init():
                normalized_fade = max(0, int(fade_ms))
                if normalized_fade > 0:
                    pygame.mixer.music.fadeout(normalized_fade)
                else:
                    pygame.mixer.music.stop()
                self._log(f"STOP fade_ms={normalized_fade}")
        except Exception as exc:
            self._set_error(str(exc))
        finally:
            self.state.playing = False
            self.state.current_track_id = ""
            self._prepared_track_id = ""

    def close(self) -> None:
        try:
            self.stop(fade_ms=0)
        finally:
            pygame = self._pygame
            if pygame is None:
                return
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
            except Exception:
                pass

    def resolve_track(self, track_id: str) -> Path | None:
        normalized_track_id = track_id.strip()
        if not normalized_track_id:
            return None
        if not self.music_dir.exists():
            return None
        available_paths = self._track_paths()
        by_name = {item.name.lower(): item for item in available_paths}
        direct_match = by_name.get(normalized_track_id.lower())
        if direct_match is not None:
            return direct_match
        stem_matches = [item for item in available_paths if item.stem.lower() == normalized_track_id.lower()]
        if len(stem_matches) == 1:
            return stem_matches[0]
        return None

    def _ensure_pygame(self):
        if self._pygame is not None:
            return self._pygame
        try:
            import pygame  # type: ignore
        except Exception:
            return None
        self._pygame = pygame
        return self._pygame

    def _ensure_mixer_ready(self, pygame) -> None:  # noqa: ANN001
        candidate_names = self._device_name_candidates()
        if pygame.mixer.get_init() and self._active_device_name in candidate_names:
            return
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        last_error: Exception | None = None
        for candidate_name in candidate_names:
            try:
                pygame.mixer.init(devicename=candidate_name)
                self._active_device_name = candidate_name
                if candidate_name:
                    self._log(f"MIXER device selected: {candidate_name}")
                else:
                    self._log("MIXER using default output device")
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("unable to initialize soundtrack mixer")

    def _device_name_candidates(self) -> list[str | None]:
        candidates: list[str | None] = []
        resolved_output = resolve_audio_device(
            "output",
            preferred_endpoint_id=self.device_endpoint_id,
            preferred_name=self.device_name,
            preferred_index=self.device_index,
        )
        resolved_index = self.device_index if resolved_output is None else resolved_output.index
        if resolved_output is not None and resolved_output.name.strip():
            candidates.append(resolved_output.name.strip())
        if self.device_name:
            candidates.append(self.device_name)
        raw_name = self._raw_output_device_name(resolved_index) if resolved_index is not None else None
        if raw_name:
            stripped_name = raw_name.strip()
            base_name = stripped_name.split("[", 1)[0].strip()
            candidates.append(base_name)
            candidates.append(stripped_name)
        candidates.append(None)
        unique_candidates: list[str | None] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = "" if candidate is None else candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)
        return unique_candidates

    def _raw_output_device_name(self, device_index: int) -> str | None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception:
            return None
        try:
            device = sd.query_devices(device_index)
        except Exception:
            return None
        if isinstance(device, dict):
            return str(device.get("name", "")).strip() or None
        return str(getattr(device, "name", "")).strip() or None

    def _set_error(self, message: str) -> None:
        self.state.last_error = message
        self._log(f"ERROR {message}")

    def _track_paths(self) -> list[Path]:
        self.music_dir.mkdir(parents=True, exist_ok=True)
        return [
            item
            for item in self.music_dir.iterdir()
            if item.is_file() and item.suffix.lower() in SUPPORTED_SOUNDTRACK_EXTENSIONS
        ]

    def _log(self, message: str) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (self.logs_dir / "music.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
