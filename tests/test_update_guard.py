from __future__ import annotations

import json

from client.services.update_guard import check_startup_update


def test_startup_update_guard_blocks_outdated_client(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "latest_version": "1.0.2",
                "minimum_required_version": "1.0.2",
                "required": True,
                "package_url": "client.zip",
                "sha256": "",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "version.json").write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "version": "1.0.1",
                "manifest_url": str(manifest_path),
            }
        ),
        encoding="utf-8",
    )

    result = check_startup_update(tmp_path)

    assert result.update_required
    assert result.local_version == "1.0.1"
    assert result.required_version == "1.0.2"


def test_startup_update_guard_allows_current_client(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "latest_version": "1.0.2",
                "minimum_required_version": "1.0.2",
                "required": True,
                "package_url": "client.zip",
                "sha256": "",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "version.json").write_text(
        json.dumps(
            {
                "product": "MAYDAY",
                "version": "1.0.2",
                "manifest_url": str(manifest_path),
            }
        ),
        encoding="utf-8",
    )

    result = check_startup_update(tmp_path)

    assert not result.update_required
    assert result.reason == "up_to_date"
