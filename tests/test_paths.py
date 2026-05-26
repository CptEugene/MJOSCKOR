from shared.constants.paths import runtime_paths


def test_runtime_paths_root_exists() -> None:
    paths = runtime_paths()
    assert paths.root_dir.name == "python-mayday"

