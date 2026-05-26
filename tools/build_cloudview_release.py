from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudview.version import CLOUDVIEW_PRODUCT, CLOUDVIEW_VERSION
from shared.constants.paths import runtime_paths


def build_cloudview_release(
    *,
    exe_path: Path | None = None,
    output_dir: Path | None = None,
    package_url_base: str = "",
    notes: list[str] | None = None,
) -> tuple[Path, Path]:
    paths = runtime_paths()
    exe_path = exe_path or paths.root_dir / "dist" / "cloudview" / "CloudviewCenter.exe"
    output_dir = output_dir or paths.root_dir / "dist" / "release"

    if not exe_path.exists():
        raise FileNotFoundError(f"CloudviewCenter.exe not found: {exe_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    package_path = output_dir / f"CloudviewCenter-{CLOUDVIEW_VERSION}.exe"
    shutil.copy2(exe_path, package_path)

    digest = _sha256_path(package_path)
    manifest_path = output_dir / "cloudview_manifest.json"
    manifest = {
        "product": CLOUDVIEW_PRODUCT,
        "latest_version": CLOUDVIEW_VERSION,
        "minimum_required_version": CLOUDVIEW_VERSION,
        "required": True,
        "package_url": _package_url(package_url_base, package_path),
        "sha256": digest,
        "notes": notes or [f"Cloudview Center {CLOUDVIEW_VERSION} update"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return package_path, manifest_path


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
    parser = argparse.ArgumentParser(description="Build Cloudview Center self-update manifest.")
    parser.add_argument("--exe-path", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--package-url-base", default="")
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    package_path, manifest_path = build_cloudview_release(
        exe_path=args.exe_path,
        output_dir=args.output_dir,
        package_url_base=args.package_url_base,
        notes=list(args.note) or None,
    )
    print(f"package={package_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
