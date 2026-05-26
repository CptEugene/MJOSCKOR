from __future__ import annotations

import shutil
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    dist_dir = project_root / "dist"

    client_exe = dist_dir / "Mayday.exe"
    server_exe = dist_dir / "MaydayServer.exe"
    client_dir = dist_dir / "client"
    server_dir = dist_dir / "server"

    client_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)

    if client_exe.exists():
        shutil.copy2(client_exe, client_dir / client_exe.name)
    if server_exe.exists():
        shutil.copy2(server_exe, server_dir / server_exe.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
