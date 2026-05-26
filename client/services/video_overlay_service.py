from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shared.constants.paths import runtime_paths


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}


@dataclass(slots=True)
class VideoOverlayState:
    available_videos: list[str] = field(default_factory=list)
    current_video_id: str = ""
    playing: bool = False
    last_error: str = ""


class VideoOverlayService:
    def __init__(self, video_dir: Path | None = None, asset_video_dir: Path | None = None) -> None:
        paths = runtime_paths()
        self.video_dir = video_dir or (paths.client_runtime_dir / "video")
        self.asset_video_dir = asset_video_dir or (paths.assets_dir / "video")
        self.state = VideoOverlayState()

    def refresh_library(self) -> list[str]:
        available: dict[str, str] = {}
        for path in self._video_paths():
            available.setdefault(path.name.lower(), path.name)
        tracks = sorted(available.values(), key=str.lower)
        self.state.available_videos = tracks
        return list(tracks)

    def resolve_video(self, video_id: str) -> Path | None:
        normalized_video_id = video_id.strip()
        if not normalized_video_id:
            self.state.last_error = "video_id_empty"
            return None
        available_paths = self._video_paths()
        by_name = {item.name.lower(): item for item in available_paths}
        direct_match = by_name.get(normalized_video_id.lower())
        if direct_match is not None:
            self.state.last_error = ""
            return direct_match
        stem_matches = [item for item in available_paths if item.stem.lower() == normalized_video_id.lower()]
        if len(stem_matches) == 1:
            self.state.last_error = ""
            return stem_matches[0]
        self.state.last_error = f"video_not_found:{normalized_video_id}"
        return None

    def _video_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        self.video_dir.mkdir(parents=True, exist_ok=True)
        search_dirs = [self.video_dir]
        if self.asset_video_dir.exists():
            search_dirs.append(self.asset_video_dir)
        for directory in search_dirs:
            for item in directory.iterdir():
                if not item.is_file() or item.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
                    continue
                key = item.name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                paths.append(item)
        return paths
