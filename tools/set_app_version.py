from __future__ import annotations

import argparse
import re
from pathlib import Path


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")


def set_app_version(version: str, *, root_dir: Path | None = None) -> None:
    normalized = version.strip()
    if not VERSION_PATTERN.match(normalized):
        raise ValueError("version must look like 1.2.3, optionally with -suffix or +build")

    root_dir = root_dir or Path(__file__).resolve().parents[1]
    pyproject_path = root_dir / "pyproject.toml"
    app_version_path = root_dir / "shared" / "constants" / "app_version.py"

    _replace_once(
        pyproject_path,
        r'(?m)^version = "[^"]+"$',
        f'version = "{normalized}"',
    )
    _replace_once(
        app_version_path,
        r'(?m)^APP_VERSION = "[^"]+"$',
        f'APP_VERSION = "{normalized}"',
    )


def _replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise ValueError(f"expected exactly one version field in {path}")
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update MAYDAY app version in all source files.")
    parser.add_argument("version", help="New version, for example 1.0.2")
    args = parser.parse_args()
    set_app_version(args.version)
    print(f"MAYDAY version set to {args.version.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
