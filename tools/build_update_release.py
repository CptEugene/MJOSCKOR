from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.constants.app_version import APP_PRODUCT, APP_VERSION, build_version_metadata
from shared.constants.paths import runtime_paths


def build_update_release(
    *,
    package_dir: Path | None = None,
    output_dir: Path | None = None,
    package_url_base: str = "",
    manifest_url: str = "",
    minimum_required_version: str | None = None,
    notes: list[str] | None = None,
) -> tuple[Path, Path]:
    paths = runtime_paths()
    package_dir = package_dir or paths.client_package_dir
    output_dir = output_dir or paths.root_dir / "dist" / "release"
    version = APP_VERSION
    minimum_required_version = minimum_required_version or version

    if not package_dir.exists():
        raise FileNotFoundError(f"MAYDAY package folder not found: {package_dir}")
    if not (package_dir / "Mayday.exe").exists():
        raise FileNotFoundError(f"Mayday.exe not found in package folder: {package_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    version_file = package_dir / "version.json"
    version_file.write_text(
        json.dumps(
            build_version_metadata(
                manifest_url=manifest_url,
                minimum_required_version=minimum_required_version,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    archive_path = output_dir / f"MAYDAY-client-{version}.zip"
    if archive_path.exists():
        archive_path.unlink()
    _zip_directory(package_dir, archive_path)

    digest = _sha256_path(archive_path)
    manifest_path = output_dir / "mayday_manifest.json"
    package_url = _package_url(package_url_base, archive_path)
    manifest = {
        "product": APP_PRODUCT,
        "latest_version": version,
        "minimum_required_version": minimum_required_version,
        "required": True,
        "package_url": package_url,
        "sha256": digest,
        "notes": notes or [f"MAYDAY {version} update package"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cloudview_manifest = paths.root_dir / "dist" / "cloudview" / "sample_mayday_manifest.json"
    cloudview_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, cloudview_manifest)
    return archive_path, manifest_path


def _zip_directory(source_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(source_dir.rglob("*")):
            if item.is_dir():
                archive.write(item, item.relative_to(source_dir).as_posix() + "/")
                continue
            if not item.is_file():
                continue
            archive.write(item, item.relative_to(source_dir).as_posix())


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_url(package_url_base: str, archive_path: Path) -> str:
    normalized_base = package_url_base.strip()
    if not normalized_base:
        return str(archive_path.resolve()).replace("\\", "/")
    if normalized_base.startswith(("http://", "https://")):
        return urljoin(normalized_base.rstrip("/") + "/", archive_path.name)
    return str((Path(normalized_base).expanduser() / archive_path.name).resolve()).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MAYDAY update zip and Cloudview manifest.")
    parser.add_argument("--package-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--package-url-base", default="")
    parser.add_argument("--manifest-url", default="")
    parser.add_argument("--minimum-required-version", default=None)
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    archive_path, manifest_path = build_update_release(
        package_dir=args.package_dir,
        output_dir=args.output_dir,
        package_url_base=args.package_url_base,
        manifest_url=args.manifest_url,
        minimum_required_version=args.minimum_required_version,
        notes=list(args.note) or None,
    )
    print(f"package={archive_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
