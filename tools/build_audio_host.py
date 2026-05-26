from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.constants.paths import runtime_paths


def build_audio_host(output_dir: Path | None = None) -> Path:
    project_root = runtime_paths().root_dir
    project_file = project_root / "native" / "MaydayAudioHost" / "MaydayAudioHost.csproj"
    output_dir = output_dir or runtime_paths().bin_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for existing in output_dir.glob("MaydayAudioHost*"):
        if existing.is_file():
            existing.unlink()

    subprocess.run(
        [
            "dotnet",
            "publish",
            str(project_file),
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "false",
            "-o",
            str(output_dir),
        ],
        check=True,
        cwd=project_root,
    )
    return output_dir


def main() -> int:
    output_dir = build_audio_host()
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
