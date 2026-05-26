from client.services.video_overlay_service import VideoOverlayService


def test_video_overlay_service_resolves_runtime_video_first(tmp_path) -> None:
    runtime_dir = tmp_path / "runtime"
    asset_dir = tmp_path / "assets"
    (runtime_dir / "mission_intro.mp4").parent.mkdir(parents=True, exist_ok=True)
    (asset_dir / "mission_intro.mp4").parent.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / "mission_intro.mp4"
    asset_path = asset_dir / "mission_intro.mp4"
    runtime_path.write_bytes(b"runtime-video")
    asset_path.write_bytes(b"asset-video")

    service = VideoOverlayService(video_dir=runtime_dir, asset_video_dir=asset_dir)

    tracks = service.refresh_library()

    assert tracks == ["mission_intro.mp4"]
    assert service.resolve_video("mission_intro.mp4") == runtime_path


def test_video_overlay_service_resolves_by_stem(tmp_path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    video_path = runtime_dir / "briefing.webm"
    video_path.write_bytes(b"video")

    service = VideoOverlayService(video_dir=runtime_dir, asset_video_dir=tmp_path / "assets")

    assert service.resolve_video("briefing") == video_path
