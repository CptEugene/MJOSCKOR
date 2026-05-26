from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from shared.constants.app_version import APP_PRODUCT, APP_VERSION
from shared.constants.paths import runtime_paths
from shared.update.versioning import compare_versions, read_json, read_manifest_version_info


@dataclass(frozen=True)
class StartupUpdateCheck:
    update_required: bool
    local_version: str
    required_version: str
    reason: str = ""


def check_startup_update(root_dir: Path | None = None) -> StartupUpdateCheck:
    root_dir = root_dir or runtime_paths().root_dir
    version_file = root_dir / "version.json"
    metadata: dict[str, object] = {}
    if version_file.exists():
        try:
            metadata = read_json(version_file)
        except Exception:
            metadata = {}

    local_version = str(metadata.get("version", APP_VERSION)).strip() or APP_VERSION
    manifest_url = str(metadata.get("manifest_url", "")).strip()
    if not manifest_url:
        return StartupUpdateCheck(False, local_version, local_version, "manifest_url_missing")

    try:
        manifest = read_manifest_version_info(manifest_url)
    except Exception as exc:
        # Do not lock users out on a temporary manifest/network failure.
        return StartupUpdateCheck(False, local_version, local_version, f"manifest_check_failed:{exc}")

    if manifest.product and manifest.product != APP_PRODUCT:
        return StartupUpdateCheck(False, local_version, local_version, "manifest_product_mismatch")

    required_version = manifest.minimum_required_version or manifest.latest_version
    if manifest.required and compare_versions(local_version, required_version) < 0:
        return StartupUpdateCheck(True, local_version, required_version, "update_required")
    return StartupUpdateCheck(False, local_version, required_version, "up_to_date")


def show_update_required_dialog(result: StartupUpdateCheck) -> None:
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("업데이트 필요")
    box.setText("업데이트가 필요합니다.")
    box.setInformativeText(
        "현재 버전으로는 접속할 수 없습니다.\n"
        "Cloudview Center에서 업데이트를 진행해 주세요.\n\n"
        f"현재 버전: {result.local_version}\n"
        f"필요 버전: {result.required_version}"
    )
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    close_button = box.button(QMessageBox.StandardButton.Close)
    if close_button is not None:
        close_button.setText("닫기")
    box.exec()
