from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.constants.app_version import APP_VERSION
from shared.constants.paths import runtime_paths


def build_server_package(package_dir: Path | None = None) -> Path:
    paths = runtime_paths()
    package_dir = package_dir or paths.server_package_dir
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "data").mkdir(parents=True, exist_ok=True)

    built_exe = paths.root_dir / "dist" / "MaydayServer.exe"
    if built_exe.exists():
        shutil.copy2(built_exe, package_dir / "MaydayServer.exe")

    if paths.server_config_file.exists():
        shutil.copy2(paths.server_config_file, package_dir / "data" / "server.toml")
    tree_path = paths.server_data_dir / "fleet_tree.txt"
    if tree_path.exists():
        shutil.copy2(tree_path, package_dir / "data" / "fleet_tree.txt")
    kneeboard_path = paths.server_data_dir / "kneeboard.txt"
    if kneeboard_path.exists():
        shutil.copy2(kneeboard_path, package_dir / "data" / "kneeboard.txt")
    notice_path = paths.server_data_dir / "notice.txt"
    if notice_path.exists():
        shutil.copy2(notice_path, package_dir / "data" / "notice.txt")

    readme = package_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "MAYDAY Python Server Package",
                "",
                "Contents:",
                "- MaydayServer.exe",
                "- runtime server config",
                "- fleet tree data",
                "- this scaffold is ready for PyInstaller bundling",
            ]
        ),
        encoding="utf-8",
    )
    manifest = package_dir / "manifest.txt"
    manifest.write_text(
        "\n".join(
            [
                "type=server",
                f"version={APP_VERSION}",
                f"exe={'yes' if (package_dir / 'MaydayServer.exe').exists() else 'no'}",
                f"tree={'yes' if (package_dir / 'data' / 'fleet_tree.txt').exists() else 'no'}",
                f"config={'yes' if (package_dir / 'data' / 'server.toml').exists() else 'no'}",
                f"kneeboard={'yes' if (package_dir / 'data' / 'kneeboard.txt').exists() else 'no'}",
                f"notice={'yes' if (package_dir / 'data' / 'notice.txt').exists() else 'no'}",
            ]
        ),
        encoding="utf-8",
    )
    return package_dir


def main() -> int:
    package_dir = build_server_package()
    print(package_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
