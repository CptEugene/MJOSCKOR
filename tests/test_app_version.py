from __future__ import annotations

import shutil
import tomllib

from shared.constants.app_version import APP_VERSION
from shared.constants.paths import runtime_paths
from tools.set_app_version import set_app_version


def test_app_version_matches_pyproject() -> None:
    pyproject_path = runtime_paths().root_dir / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    assert data["project"]["version"] == APP_VERSION


def test_set_app_version_updates_known_version_files(tmp_path) -> None:
    root = runtime_paths().root_dir
    sandbox = tmp_path / "project"
    (sandbox / "shared" / "constants").mkdir(parents=True)
    shutil.copy2(root / "pyproject.toml", sandbox / "pyproject.toml")
    shutil.copy2(root / "shared" / "constants" / "app_version.py", sandbox / "shared" / "constants" / "app_version.py")

    set_app_version("7.8.9", root_dir=sandbox)

    with (sandbox / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    app_version_text = (sandbox / "shared" / "constants" / "app_version.py").read_text(
        encoding="utf-8"
    )

    assert pyproject["project"]["version"] == "7.8.9"
    assert 'APP_VERSION = "7.8.9"' in app_version_text
