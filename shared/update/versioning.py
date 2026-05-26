from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ManifestVersionInfo:
    product: str
    latest_version: str
    minimum_required_version: str
    required: bool


def compare_versions(left: str, right: str) -> int:
    """Return -1, 0, or 1 when comparing dotted semantic-ish versions."""

    def normalize(value: str) -> list[int]:
        parts: list[int] = []
        token = ""
        for char in value:
            if char.isdigit():
                token += char
            elif token:
                parts.append(int(token))
                token = ""
        if token:
            parts.append(int(token))
        return parts or [0]

    left_parts = normalize(left)
    right_parts = normalize(right)
    size = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (size - len(left_parts)))
    right_parts.extend([0] * (size - len(right_parts)))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_manifest_version_info(manifest_url: str, *, timeout: float = 6.0) -> ManifestVersionInfo:
    payload = _read_url_or_file(manifest_url, timeout=timeout)
    data = json.loads(payload.decode("utf-8-sig"))
    latest_version = str(data.get("latest_version", "")).strip()
    minimum_required_version = str(
        data.get("minimum_required_version", latest_version)
    ).strip()
    return ManifestVersionInfo(
        product=str(data.get("product", "MAYDAY")).strip() or "MAYDAY",
        latest_version=latest_version,
        minimum_required_version=minimum_required_version,
        required=bool(data.get("required", True)),
    )


def _read_url_or_file(value: str, *, timeout: float) -> bytes:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(value, headers={"User-Agent": "MAYDAY/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    if parsed.scheme == "file":
        path = Path(urllib.request.url2pathname(parsed.path))
    else:
        path = Path(value).expanduser()
    return path.read_bytes()
