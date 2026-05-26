from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


APP_PRODUCT = "MAYDAY"
APP_VERSION = "1.5.4"
UPDATE_PROTOCOL_VERSION = 1


def build_version_metadata(
    *,
    manifest_url: str = "",
    minimum_required_version: str | None = None,
) -> dict[str, Any]:
    return {
        "product": APP_PRODUCT,
        "version": APP_VERSION,
        "minimum_required_version": minimum_required_version or APP_VERSION,
        "update_protocol_version": UPDATE_PROTOCOL_VERSION,
        "manifest_url": manifest_url,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
