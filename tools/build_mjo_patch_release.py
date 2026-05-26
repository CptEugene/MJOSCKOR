from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


PATCH_PRODUCT = "MJO_KOREAN_PATCH"
PATCH_VERSION = "1.0.0"


def build_mjo_patch_release(
    *,
    source_zip: Path | None = None,
    output_dir: Path | None = None,
    package_url_base: str = "",
    version: str = PATCH_VERSION,
    notes: list[str] | None = None,
) -> tuple[Path, Path]:
    root_dir = Path(__file__).resolve().parents[1]
    output_dir = output_dir or root_dir / "dist" / "release"
    source_zip = source_zip or _default_source_zip(root_dir)
    if not source_zip.exists():
        raise FileNotFoundError(f"MJO patch zip not found: {source_zip}")

    output_dir.mkdir(parents=True, exist_ok=True)
    package_path = output_dir / source_zip.name
    shutil.copy2(source_zip, package_path)

    manifest_path = output_dir / "mjo_patch_manifest.json"
    manifest = {
        "product": PATCH_PRODUCT,
        "latest_version": version,
        "minimum_required_version": version,
        "required": True,
        "package_url": _package_url(package_url_base, package_path),
        "sha256": _sha256_path(package_path),
        "target": "StarCitizenRoot",
        "notes": notes or [f"MJO Korean Patch {version}"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return package_path, manifest_path


def _default_source_zip(root_dir: Path) -> Path:
    candidates = [
        root_dir / "LIVE.zip",
        root_dir.parent / "LIVE.zip",
        root_dir.parent.parent / "LIVE.zip",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_url(package_url_base: str, package_path: Path) -> str:
    normalized_base = package_url_base.strip()
    if not normalized_base:
        return str(package_path.resolve()).replace("\\", "/")
    if normalized_base.startswith(("http://", "https://")):
        return urljoin(normalized_base.rstrip("/") + "/", package_path.name)
    return str((Path(normalized_base).expanduser() / package_path.name).resolve()).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MJO Korean patch manifest.")
    parser.add_argument("--source-zip", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--package-url-base", default="")
    parser.add_argument("--version", default=PATCH_VERSION)
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    package_path, manifest_path = build_mjo_patch_release(
        source_zip=args.source_zip,
        output_dir=args.output_dir,
        package_url_base=args.package_url_base,
        version=args.version,
        notes=list(args.note) or None,
    )
    print(f"package={package_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
