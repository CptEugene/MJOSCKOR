from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
import ctypes
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cloudview.version import CLOUDVIEW_PRODUCT, CLOUDVIEW_VERSION
from cloudview.services.star_citizen_locator import (
    detect_star_citizen_install,
    resolve_star_citizen_channel_dir,
)
from shared.update.versioning import compare_versions


ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class UpdateManifest:
    product: str
    latest_version: str
    minimum_required_version: str
    required: bool
    package_url: str
    sha256: str
    notes: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateManifest":
        notes = data.get("notes", [])
        if isinstance(notes, str):
            notes = [notes]
        return cls(
            product=str(data.get("product", "MAYDAY")),
            latest_version=str(data.get("latest_version", "")).strip(),
            minimum_required_version=str(
                data.get("minimum_required_version", data.get("latest_version", ""))
            ).strip(),
            required=bool(data.get("required", True)),
            package_url=str(data.get("package_url", "")).strip(),
            sha256=str(data.get("sha256", "")).strip().lower(),
            notes=tuple(str(item) for item in notes),
        )


def default_cloudview_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "MJO" / "Cloudview Center"
    return Path.home() / "MJO" / "Cloudview Center"


def _legacy_cloudview_config_candidates() -> list[Path]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "cloudview_config.json")
    candidates.append(Path(__file__).resolve().parents[2] / "runtime" / "cloudview" / "cloudview_config.json")
    return candidates


def default_manifest_url(config_path: Path | None = None) -> str:
    env_url = os.environ.get("CLOUDVIEW_MAYDAY_MANIFEST_URL", "").strip()
    if env_url:
        return env_url

    for source_path in _update_source_candidates(config_path):
        manifest_url = _read_manifest_url_source(source_path)
        if manifest_url:
            return manifest_url

    for manifest_path in _sample_manifest_candidates(config_path):
        if manifest_path.exists():
            return str(manifest_path)
    return ""


def default_cloudview_manifest_url(config_path: Path | None = None) -> str:
    env_url = os.environ.get("CLOUDVIEW_CENTER_MANIFEST_URL", "").strip()
    if env_url:
        return env_url

    for source_path in _update_source_candidates(config_path):
        manifest_url = _read_manifest_url_source(source_path, key="cloudview_manifest_url")
        if manifest_url:
            return manifest_url
    return "http://14.206.48.12:42000/cloudview_manifest.json"


def default_mjo_patch_manifest_url(config_path: Path | None = None) -> str:
    env_url = os.environ.get("CLOUDVIEW_MJO_PATCH_MANIFEST_URL", "").strip()
    if env_url:
        return env_url

    for source_path in _update_source_candidates(config_path):
        manifest_url = _read_manifest_url_source(source_path, key="mjo_patch_manifest_url")
        if manifest_url:
            return manifest_url
    return "http://14.206.48.12:42000/mjo_patch_manifest.json"


def _update_source_candidates(config_path: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if config_path is not None:
        candidates.append(config_path.parent / "cloudview_update_source.json")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "cloudview_update_source.json")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "cloudview" / "update_source.json")
    project_root = Path(__file__).resolve().parents[2]
    candidates.append(project_root / "assets" / "cloudview" / "update_source.json")
    return candidates


def _sample_manifest_candidates(config_path: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if config_path is not None:
        candidates.append(config_path.parent / "sample_mayday_manifest.json")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "sample_mayday_manifest.json")
    project_root = Path(__file__).resolve().parents[2]
    candidates.append(project_root / "dist" / "cloudview" / "sample_mayday_manifest.json")
    candidates.append(project_root / "dist" / "release" / "mayday_manifest.json")
    return candidates


def _read_manifest_url_source(path: Path, *, key: str = "manifest_url") -> str:
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    return str(data.get(key, "")).strip()


def default_install_dir() -> Path:
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        return Path(program_files) / "Cloudview" / "MAYDAY"
    system_drive = os.environ.get("SystemDrive")
    if system_drive:
        return Path(system_drive) / "Program Files" / "Cloudview" / "MAYDAY"
    return Path.home() / "MJO" / "MAYDAY"


class CloudviewConfig:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_cloudview_dir() / "cloudview_config.json"
        self.install_dir = default_install_dir()
        self.manifest_url = default_manifest_url(self.config_path)
        self.cloudview_manifest_url = default_cloudview_manifest_url(self.config_path)
        self.mjo_patch_manifest_url = default_mjo_patch_manifest_url(self.config_path)
        self.patch_source = ""
        self.patch_target = ""
        if self.config_path.exists():
            self.load()
        elif config_path is None:
            self._migrate_legacy_config()

    def load(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.install_dir = Path(str(data.get("install_dir", self.install_dir)))
        self.manifest_url = str(data.get("manifest_url", self.manifest_url)).strip() or default_manifest_url(
            self.config_path
        )
        self.cloudview_manifest_url = str(
            data.get("cloudview_manifest_url", self.cloudview_manifest_url)
        ).strip() or default_cloudview_manifest_url(self.config_path)
        self.mjo_patch_manifest_url = str(
            data.get("mjo_patch_manifest_url", self.mjo_patch_manifest_url)
        ).strip() or default_mjo_patch_manifest_url(self.config_path)
        self.patch_source = str(data.get("patch_source", self.patch_source))
        self.patch_target = str(data.get("patch_target", self.patch_target))

    def _migrate_legacy_config(self) -> None:
        for legacy_path in _legacy_cloudview_config_candidates():
            if not legacy_path.exists() or legacy_path == self.config_path:
                continue
            try:
                data = json.loads(legacy_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            self.install_dir = Path(str(data.get("install_dir", self.install_dir)))
            self.manifest_url = str(data.get("manifest_url", self.manifest_url)).strip() or default_manifest_url(
                self.config_path
            )
            self.cloudview_manifest_url = str(
                data.get("cloudview_manifest_url", self.cloudview_manifest_url)
            ).strip() or default_cloudview_manifest_url(self.config_path)
            self.mjo_patch_manifest_url = str(
                data.get("mjo_patch_manifest_url", self.mjo_patch_manifest_url)
            ).strip() or default_mjo_patch_manifest_url(self.config_path)
            self.patch_source = str(data.get("patch_source", self.patch_source))
            self.patch_target = str(data.get("patch_target", self.patch_target))
            self.save()
            return

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {
                    "install_dir": str(self.install_dir),
                    "manifest_url": self.manifest_url,
                    "cloudview_manifest_url": self.cloudview_manifest_url,
                    "mjo_patch_manifest_url": self.mjo_patch_manifest_url,
                    "patch_source": self.patch_source,
                    "patch_target": self.patch_target,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


class UpdateManager:
    def __init__(self, config: CloudviewConfig | None = None) -> None:
        self.config = config or CloudviewConfig()
        self.base_dir = self.config.config_path.parent
        self.downloads_dir = self.base_dir / "downloads"
        self.backups_dir = self.base_dir / "backups"
        self.patch_backup_dir = self.base_dir / "mjo_patch" / "backups"
        self._resolved_mjo_patch_manifest: UpdateManifest | None = None

    def read_installed_version(self, install_dir: Path | None = None) -> str | None:
        install_dir = install_dir or self.config.install_dir
        version_file = install_dir / "version.json"
        if version_file.exists():
            try:
                data = json.loads(version_file.read_text(encoding="utf-8"))
                version = str(data.get("version", "")).strip()
                if version:
                    return version
            except Exception:
                pass
        if (install_dir / "Mayday.exe").exists():
            return "unknown"
        return None

    def fetch_manifest(self, manifest_url: str) -> UpdateManifest:
        if not manifest_url.strip():
            raise ValueError("manifest URL이 비어 있습니다.")
        payload = self._read_url_or_file(manifest_url)
        try:
            data = json.loads(payload.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"manifest JSON을 읽을 수 없습니다: {exc}") from exc
        manifest = UpdateManifest.from_dict(data)
        if not manifest.latest_version:
            raise ValueError("manifest에 latest_version이 없습니다.")
        if not manifest.package_url:
            raise ValueError("manifest에 package_url이 없습니다.")
        return manifest

    def needs_update(self, installed_version: str | None, manifest: UpdateManifest) -> bool:
        if installed_version is None or installed_version == "unknown":
            return True
        return compare_versions(installed_version, manifest.minimum_required_version) < 0

    def fetch_cloudview_manifest(self) -> UpdateManifest:
        return self.fetch_manifest(self.config.cloudview_manifest_url)

    def needs_cloudview_update(self, manifest: UpdateManifest) -> bool:
        version_compare = compare_versions(CLOUDVIEW_VERSION, manifest.latest_version)
        if version_compare < 0:
            return True
        if version_compare > 0:
            return False
        if not manifest.sha256 or not getattr(sys, "frozen", False):
            return False
        try:
            return self._sha256_path(Path(sys.executable)) != manifest.sha256.lower()
        except OSError:
            return False

    def fetch_mjo_patch_manifest(self) -> UpdateManifest:
        return self.fetch_manifest(self.config.mjo_patch_manifest_url)

    def read_installed_mjo_patch_version(self) -> str | None:
        try:
            version_file = self.mjo_patch_version_path()
        except ValueError:
            return None
        if not version_file.exists():
            legacy_version_file = self._legacy_mjo_patch_version_path()
            if legacy_version_file.exists():
                version_file = legacy_version_file
            else:
                if self._patch_manifest_path().exists():
                    return "unknown"
                return None
        try:
            data = json.loads(version_file.read_text(encoding="utf-8"))
        except Exception:
            return "unknown"
        version = str(data.get("version", "")).strip()
        return version or "unknown"

    def needs_mjo_patch_update(self, installed_version: str | None, manifest: UpdateManifest) -> bool:
        if installed_version is None or installed_version == "unknown":
            return True
        return compare_versions(installed_version, manifest.minimum_required_version) < 0

    def install_requires_elevation(self, install_dir: Path | None = None) -> bool:
        if os.name != "nt" or self.is_process_elevated():
            return False
        target = (install_dir or self.config.install_dir).resolve()
        protected_roots: list[Path] = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            value = os.environ.get(env_name)
            if value:
                protected_roots.append(Path(value).resolve())
        system_drive = os.environ.get("SystemDrive")
        if system_drive:
            protected_roots.append((Path(system_drive) / "Program Files").resolve())
        return any(target == root or root in target.parents for root in protected_roots)

    def is_process_elevated(self) -> bool:
        if os.name != "nt":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def relaunch_as_admin(self, extra_args: list[str] | None = None) -> bool:
        if os.name != "nt":
            return False
        executable = Path(sys.executable).resolve()
        extra_args = extra_args or []
        if getattr(sys, "frozen", False):
            parameters = subprocess.list2cmdline(extra_args)
        else:
            parameters = subprocess.list2cmdline([*sys.argv, *extra_args])
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(executable),
                parameters,
                str(executable.parent),
                1,
            )
            return int(result) > 32
        except Exception:
            return False

    def download_package(
        self,
        manifest: UpdateManifest,
        progress: ProgressCallback | None = None,
    ) -> Path:
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(urllib.parse.urlparse(manifest.package_url).path).name or "mayday-package.zip"
        target = self.downloads_dir / filename
        self._emit(progress, "패키지 다운로드 준비...", 5)

        parsed = urllib.parse.urlparse(manifest.package_url)
        if parsed.scheme in {"http", "https"}:
            request = urllib.request.Request(manifest.package_url, headers={"User-Agent": "CloudviewCenter/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as handle:
                total = int(response.headers.get("Content-Length", "0") or "0")
                received = 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    if total:
                        self._emit(progress, "패키지 다운로드 중...", min(80, 5 + int(received / total * 70)))
        else:
            source = self._resolve_local_path(manifest.package_url)
            if not source.exists():
                raise FileNotFoundError(f"패키지 파일을 찾을 수 없습니다: {source}")
            shutil.copy2(source, target)
            self._emit(progress, "로컬 패키지 복사 완료", 80)

        self._verify_sha256(target, manifest.sha256)
        self._emit(progress, "패키지 검증 완료", 90)
        return target

    def _extract_safe_archive(self, archive_path: Path, target_dir: Path) -> None:
        target_root = target_dir.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                relative = self._safe_archive_relative_path(info.filename)
                if relative is None:
                    continue
                destination = (target_root / relative).resolve()
                if destination != target_root and target_root not in destination.parents:
                    raise ValueError(f"압축파일에 안전하지 않은 경로가 있습니다: {info.filename}")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                self._ensure_directory(destination.parent)
                with archive.open(info) as source_handle, destination.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)

    def download_cloudview_package(
        self,
        manifest: UpdateManifest,
        progress: ProgressCallback | None = None,
    ) -> Path:
        return self.download_package(manifest, progress)

    def download_mjo_patch_package(
        self,
        manifest: UpdateManifest,
        progress: ProgressCallback | None = None,
    ) -> Path:
        return self.download_package(manifest, progress)

    def apply_cloudview_update(self, package_path: Path, manifest: UpdateManifest) -> None:
        if os.name != "nt":
            raise RuntimeError("Cloudview self update is currently supported on Windows only.")
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Cloudview self update can only replace the packaged exe build.")

        current_exe = Path(sys.executable).resolve()
        log_path = self.base_dir / "cloudview_self_update.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        parameters = subprocess.list2cmdline(
            [
                "--apply-cloudview-update",
                "--parent-pid",
                str(os.getpid()),
                "--target-exe",
                str(current_exe),
                "--expected-sha256",
                manifest.sha256,
                "--log-path",
                str(log_path),
            ]
        )
        package_path = package_path.resolve()
        if self._path_requires_elevation(current_exe):
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(package_path),
                parameters,
                str(package_path.parent),
                0,
            )
            if int(result) <= 32:
                raise RuntimeError("Cloudview updater elevation request was cancelled or failed.")
            return
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            str(package_path),
            parameters,
            str(package_path.parent),
            0,
        )
        if int(result) <= 32:
            raise RuntimeError(f"Cloudview updater launch failed: ShellExecuteW={int(result)}")

    def install_package(
        self,
        package_path: Path,
        manifest: UpdateManifest,
        progress: ProgressCallback | None = None,
    ) -> None:
        install_dir = self.config.install_dir
        self._validate_mayday_install_dir(install_dir)
        self._emit(progress, "MAYDAY 실행 상태 확인...", 5)
        self._stop_mayday_if_running()

        self._ensure_directory(self.backups_dir)
        self._ensure_directory(install_dir.parent)
        backup_dir: Path | None = None
        installed_ok = False
        if install_dir.exists() and any(install_dir.iterdir()):
            backup_dir = self._unique_backup_dir(self.backups_dir, "MAYDAY")
            self._emit(progress, "기존 설치 백업 중...", 15)
            shutil.copytree(install_dir, backup_dir)

        preserve_dir = Path(tempfile.mkdtemp(prefix="cloudview_preserve_"))
        try:
            self._preserve_user_files(install_dir, preserve_dir)
            with tempfile.TemporaryDirectory(prefix="cloudview_extract_") as temp_name:
                temp_dir = Path(temp_name)
                self._emit(progress, "패키지 압축 해제 중...", 40)
                self._extract_safe_archive(package_path, temp_dir)
                source_dir = self._find_package_root(temp_dir)

                if install_dir.exists():
                    self._clear_directory(install_dir)
                install_dir.mkdir(parents=True, exist_ok=True)
                self._emit(progress, "새 버전 설치 중...", 65)
                self._copy_directory_contents(source_dir, install_dir)
                self._restore_user_files(install_dir, preserve_dir)
                self._ensure_runtime_media_dirs(install_dir)
                self._write_version_file(install_dir, manifest)
                installed_ok = True
        except Exception:
            if backup_dir and backup_dir.exists():
                self._clear_directory(install_dir)
                self._copy_directory_contents(backup_dir, install_dir)
            raise
        finally:
            shutil.rmtree(preserve_dir, ignore_errors=True)
            if installed_ok:
                self._clear_backup_directory(self.backups_dir)

        self._emit(progress, "업데이트 완료", 100)

    def launch_mayday(self) -> None:
        exe_path = self.config.install_dir / "Mayday.exe"
        if not exe_path.exists():
            raise FileNotFoundError(f"Mayday.exe를 찾을 수 없습니다: {exe_path}")
        if os.name == "nt":
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(exe_path),
                "",
                str(exe_path.parent),
                1,
            )
            if int(result) <= 32:
                raise RuntimeError("MAYDAY 관리자 권한 실행 요청이 취소되었거나 실패했습니다.")
            return
        subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent), close_fds=True)

    def _validate_mayday_install_dir(self, install_dir: Path) -> None:
        target = install_dir.expanduser().resolve(strict=False)
        anchor = Path(target.anchor).resolve(strict=False) if target.anchor else None
        if anchor is not None and target == anchor:
            raise ValueError(f"MAYDAY 설치 경로가 드라이브 루트입니다: {target}")

        dangerous_roots = {
            Path.home().resolve(strict=False),
            (Path.home() / "Desktop").resolve(strict=False),
            (Path.home() / "Documents").resolve(strict=False),
            (Path.home() / "Downloads").resolve(strict=False),
        }
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "SystemRoot", "WINDIR"):
            value = os.environ.get(env_name)
            if value:
                dangerous_roots.add(Path(value).resolve(strict=False))
        if target in dangerous_roots:
            raise ValueError(f"MAYDAY 설치 경로로 사용할 수 없는 보호 폴더입니다: {target}")

        if "mayday" not in target.name.lower():
            raise ValueError(f"MAYDAY 설치 경로의 마지막 폴더 이름에 MAYDAY가 포함되어야 합니다: {target}")

    def _path_requires_elevation(self, path: Path) -> bool:
        if os.name != "nt" or self.is_process_elevated():
            return False
        target = path.resolve()
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            value = os.environ.get(env_name)
            if not value:
                continue
            root = Path(value).resolve()
            if target == root or root in target.parents:
                return True
        return False

    def install_mjo_patch_placeholder(
        self,
        progress: ProgressCallback | None = None,
        manifest_override: UpdateManifest | None = None,
    ) -> str:
        self.config.save()
        self._emit(progress, "MJO 한글패치 준비 중...", 5)
        source = self._resolve_mjo_patch_source(progress)
        manifest = self._resolved_mjo_patch_manifest or manifest_override
        configured_target = (
            Path(self.config.patch_target).expanduser() if self.config.patch_target else detect_star_citizen_install()
        )
        target = self._resolve_mjo_patch_target_dir(configured_target)
        if target is None:
            raise FileNotFoundError("스타시티즌 설치 경로를 찾지 못했습니다.")
        self._validate_patch_archive(source)
        self._emit(progress, "MJO 한글패치 적용 중...", 60)

        backup_dir = self._unique_backup_dir(self.patch_backup_dir, "patch")
        installed_files: list[dict[str, object]] = []
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                relative = self._safe_archive_relative_path(info.filename)
                if relative is None:
                    continue
                destination = target / relative
                backup_file = backup_dir / relative
                backed_up = destination.exists()
                backup_kind = ""
                if backed_up:
                    self._ensure_directory(backup_file.parent)
                    if destination.is_dir():
                        backup_kind = "dir"
                        if backup_file.exists():
                            self._remove_path(backup_file)
                        shutil.copytree(destination, backup_file)
                        shutil.rmtree(destination)
                    else:
                        backup_kind = "file"
                        shutil.copy2(destination, backup_file)
                self._replace_archive_member(archive, info, destination)
                installed_files.append(
                    {
                        "relative": relative.as_posix(),
                        "backed_up": backed_up,
                        "backup_kind": backup_kind,
                    }
                )

        manifest_files = [
            {
                "relative": str(item["relative"]),
                "backed_up": bool(item["backed_up"]),
                "backup_kind": "",
            }
            for item in installed_files
        ]
        self._clear_backup_directory(self.patch_backup_dir)
        self._ensure_directory(self.patch_backup_dir)
        self._patch_manifest_path().write_text(
            json.dumps(
                {
                    "source": str(source),
                    "target": str(target),
                    "backup_dir": "",
                    "installed_at": datetime.now().isoformat(timespec="seconds"),
                    "files": manifest_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.config.patch_source = str(source)
        self.config.patch_target = str(target)
        self.config.save()
        self._write_mjo_patch_version_file(target, source, manifest)
        self._emit(progress, "MJO 한글패치 설치 완료", 100)
        return f"MJO 한글패치 설치 완료: {target}"

    def uninstall_mjo_patch_placeholder(self) -> str:
        manifest_path = self._patch_manifest_path()
        if not manifest_path.exists():
            raise FileNotFoundError("설치된 MJO 한글패치 기록이 없습니다.")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        target = Path(str(data["target"]))
        backup_dir_value = str(data.get("backup_dir", "")).strip()
        backup_dir = Path(backup_dir_value) if backup_dir_value else None
        restored = 0
        removed = 0
        for item in reversed(list(data.get("files", []))):
            relative = Path(str(item["relative"]))
            destination = target / relative
            backup_file = backup_dir / relative if backup_dir is not None else None
            if bool(item.get("backed_up")) and backup_file is not None and backup_file.exists():
                self._remove_path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if str(item.get("backup_kind", "")) == "dir" or backup_file.is_dir():
                    shutil.copytree(backup_file, destination)
                else:
                    shutil.copy2(backup_file, destination)
                restored += 1
            elif not bool(item.get("backed_up")) and destination.exists():
                self._remove_path(destination)
                removed += 1
        manifest_path.unlink(missing_ok=True)
        self.mjo_patch_version_path(target).unlink(missing_ok=True)
        self._legacy_mjo_patch_version_path().unlink(missing_ok=True)
        self.config.save()
        return f"MJO 한글패치 삭제 완료: 복구 {restored}개, 제거 {removed}개"

    def detect_star_citizen_patch_target(self) -> Path | None:
        return self._resolve_mjo_patch_target_dir(detect_star_citizen_install())

    def detect_mjo_patch_source(self) -> Path | None:
        for candidate in self._mjo_patch_source_candidates():
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def patch_requires_elevation(self, target_dir: Path | None = None) -> bool:
        target = target_dir or (Path(self.config.patch_target) if self.config.patch_target else None)
        if target is None:
            target = detect_star_citizen_install()
        try:
            target = self._resolve_mjo_patch_target_dir(target)
        except ValueError:
            return False
        if target is None:
            return False
        return self._path_requires_elevation(target)

    def _patch_manifest_path(self) -> Path:
        return self.patch_backup_dir / "mjo_patch_manifest.json"

    def mjo_patch_version_path(self, target: Path | None = None) -> Path:
        target = target or self._mjo_patch_version_target()
        if target is not None:
            return target / "data" / "Localization" / "korean_(south_korea)" / "mjo_patch_version.json"
        return self._legacy_mjo_patch_version_path()

    def _legacy_mjo_patch_version_path(self) -> Path:
        return self.base_dir / "mjo_patch" / "version.json"

    def _mjo_patch_version_target(self) -> Path | None:
        try:
            if self.config.patch_target:
                return self._resolve_mjo_patch_target_dir(Path(self.config.patch_target).expanduser())
            return self._resolve_mjo_patch_target_dir(detect_star_citizen_install())
        except ValueError:
            return None

    def _resolve_mjo_patch_source(self, progress: ProgressCallback | None = None) -> Path:
        self._resolved_mjo_patch_manifest = None
        if self.config.patch_source:
            source = Path(self.config.patch_source).expanduser()
            if source.exists():
                return source
        source = self.detect_mjo_patch_source()
        if source is not None:
            return source
        manifest = self.fetch_mjo_patch_manifest()
        self._resolved_mjo_patch_manifest = manifest
        return self.download_mjo_patch_package(manifest, progress)

    def _mjo_patch_source_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "LIVE.zip")
        root = Path(__file__).resolve().parents[2]
        candidates.extend(
            [
                self.config.config_path.parent / "LIVE.zip",
                Path.cwd() / "LIVE.zip",
                root / "LIVE.zip",
                root.parent / "LIVE.zip",
                root.parent.parent / "LIVE.zip",
            ]
        )
        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = str(candidate).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(candidate)
        return unique

    def _resolve_mjo_patch_target_dir(self, target: Path | None) -> Path | None:
        if target is None:
            return None
        channel_dir = resolve_star_citizen_channel_dir(target.expanduser())
        if channel_dir is None:
            raise ValueError(f"Star Citizen 채널 폴더를 찾을 수 없습니다: {target}")
        return channel_dir

    def _validate_star_citizen_root(self, target: Path) -> None:
        if not target.exists():
            raise FileNotFoundError(f"스타시티즌 경로를 찾을 수 없습니다: {target}")
        has_channel = any((target / channel).exists() for channel in ("LIVE", "PTU", "EPTU"))
        if target.name.lower() != "starcitizen" and not has_channel:
            raise ValueError(f"스타시티즌 루트 폴더가 아닙니다: {target}")

    def _validate_patch_archive(self, source: Path) -> None:
        with zipfile.ZipFile(source) as archive:
            names = {info.filename.replace("\\", "/") for info in archive.infolist()}
        if "user.cfg" not in names or not any(name.startswith("data/Localization/") for name in names):
            raise ValueError("MJO 한글패치 압축파일 구조가 올바르지 않습니다.")

    def _safe_archive_relative_path(self, name: str) -> Path | None:
        raw_name = name.replace("\\", "/")
        if raw_name.endswith("/"):
            return None
        normalized = raw_name.strip("/")
        if not normalized:
            return None
        relative = Path(normalized)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ValueError(f"압축파일에 안전하지 않은 경로가 있습니다: {name}")
        return relative

    def _replace_archive_member(
        self,
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        destination: Path,
    ) -> None:
        self._ensure_directory(destination.parent)
        if destination.exists() and destination.is_dir():
            self._remove_path(destination)
        temp_path = destination.with_name(f".{destination.name}.cloudview_tmp_{os.getpid()}")
        temp_path.unlink(missing_ok=True)
        try:
            with archive.open(info) as source_handle, temp_path.open("wb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
            if destination.exists() and destination.is_file():
                try:
                    destination.chmod(0o666)
                except Exception:
                    pass
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)

    def _remove_path(self, path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
            return
        try:
            path.chmod(0o666)
        except Exception:
            pass
        path.unlink()

    def _ensure_directory(self, directory: Path) -> None:
        directory = directory.resolve()
        current = Path(directory.anchor)
        for part in directory.parts[1:]:
            current = current / part
            if current.exists() and not current.is_dir():
                self._remove_path(current)
            current.mkdir(exist_ok=True)

    def _unique_backup_dir(self, root: Path, prefix: str) -> Path:
        self._ensure_directory(root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = root / f"{prefix}_{stamp}"
        if not candidate.exists():
            return candidate
        for index in range(1, 1000):
            candidate = root / f"{prefix}_{stamp}_{index:03d}"
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"Could not create a unique backup directory under {root}")

    def _clear_backup_directory(self, root: Path) -> None:
        if not root.exists():
            return
        for item in root.iterdir():
            if item.name == "mjo_patch_manifest.json":
                continue
            self._remove_path(item)

    def _read_url_or_file(self, value: str) -> bytes:
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme in {"http", "https"}:
            request = urllib.request.Request(value, headers={"User-Agent": "CloudviewCenter/1.0"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read()
        path = self._resolve_local_path(value)
        if not path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
        return path.read_bytes()

    def _resolve_local_path(self, value: str) -> Path:
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme == "file":
            return Path(urllib.request.url2pathname(parsed.path))
        return Path(value).expanduser()

    def _verify_sha256(self, path: Path, expected: str) -> None:
        if not expected or expected in {"package_sha256_hash", "sha256"}:
            return
        actual = self._sha256_path(path)
        if actual != expected.lower():
            raise ValueError(f"SHA256 검증 실패: expected={expected}, actual={actual}")

    def _sha256_path(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower()

    def _stop_mayday_if_running(self) -> None:
        if os.name != "nt":
            return
        subprocess.run(
            ["taskkill", "/IM", "Mayday.exe", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _preserve_user_files(self, install_dir: Path, preserve_dir: Path) -> None:
        candidates = [
            Path("client.toml"),
            Path("runtime") / "client" / "data",
            Path("runtime") / "client" / "music",
            Path("runtime") / "client" / "video",
        ]
        for relative in candidates:
            source = install_dir / relative
            if not source.exists():
                continue
            target = preserve_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)

    def _restore_user_files(self, install_dir: Path, preserve_dir: Path) -> None:
        if not preserve_dir.exists():
            return
        for source in preserve_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(preserve_dir)
            target = install_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _find_package_root(self, temp_dir: Path) -> Path:
        entries = [item for item in temp_dir.iterdir()]
        if len(entries) == 1 and entries[0].is_dir() and not (temp_dir / "Mayday.exe").exists():
            return entries[0]
        return temp_dir

    def _clear_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for item in directory.iterdir():
            self._remove_path(item)

    def _copy_directory_contents(self, source: Path, target: Path) -> None:
        self._ensure_directory(target)
        for item in source.iterdir():
            destination = target / item.name
            if item.is_dir():
                if destination.exists() and not destination.is_dir():
                    self._remove_path(destination)
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                self._ensure_directory(destination.parent)
                if destination.exists() and destination.is_dir():
                    self._remove_path(destination)
                shutil.copy2(item, destination)

    def _ensure_runtime_media_dirs(self, install_dir: Path) -> None:
        (install_dir / "runtime" / "client" / "music").mkdir(parents=True, exist_ok=True)
        (install_dir / "runtime" / "client" / "video").mkdir(parents=True, exist_ok=True)

    def _write_version_file(self, install_dir: Path, manifest: UpdateManifest) -> None:
        install_dir.mkdir(parents=True, exist_ok=True)
        (install_dir / "version.json").write_text(
            json.dumps(
                {
                    "product": manifest.product,
                    "version": manifest.latest_version,
                    "minimum_required_version": manifest.minimum_required_version,
                    "required": manifest.required,
                    "manifest_url": self.config.manifest_url,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_mjo_patch_version_file(
        self,
        target: Path,
        source: Path,
        manifest: UpdateManifest | None,
    ) -> None:
        version_file = self.mjo_patch_version_path(target)
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(
            json.dumps(
                {
                    "product": manifest.product if manifest else "MJO_KOREAN_PATCH",
                    "version": manifest.latest_version if manifest else "unknown",
                    "minimum_required_version": manifest.minimum_required_version if manifest else "unknown",
                    "required": manifest.required if manifest else True,
                    "manifest_url": self.config.mjo_patch_manifest_url,
                    "package_url": manifest.package_url if manifest else str(source),
                    "sha256": manifest.sha256 if manifest else "",
                    "source": str(source),
                    "target": str(target),
                    "installed_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _emit(self, progress: ProgressCallback | None, message: str, percent: int) -> None:
        if progress:
            progress(message, percent)
