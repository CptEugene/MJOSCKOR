from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path
import shutil
import sys
import time

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from client.services.font_loader import load_app_font
from cloudview.ui.main_window import CloudviewCenterWindow
from shared.constants.paths import runtime_paths
from shared.runtime.parent_watchdog import start_pyinstaller_parent_watchdog


SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x00000102


def _cloudview_icon_path() -> Path:
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "cloudview" / "icons" / "ccicon_rounded.png")
    candidates.append(runtime_paths().assets_dir / "cloudview" / "icons" / "ccicon_rounded.png")
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / "cloudview" / "icons" / "ccicon_rounded.png")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _write_update_log(log_path: Path | None, message: str) -> None:
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _wait_for_process_exit(pid: int, log_path: Path | None) -> None:
    if pid <= 0:
        return
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        _write_update_log(log_path, f"Parent process {pid} is already closed.")
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, 60_000)
        if result == WAIT_OBJECT_0:
            _write_update_log(log_path, f"Parent process {pid} exited.")
        elif result == WAIT_TIMEOUT:
            _write_update_log(log_path, f"Timed out waiting for parent process {pid}.")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _arg_value(name: str) -> str:
    try:
        index = sys.argv.index(name)
        return sys.argv[index + 1]
    except Exception:
        return ""


def _apply_cloudview_update_from_download() -> int:
    target = Path(_arg_value("--target-exe"))
    expected_sha256 = _arg_value("--expected-sha256").strip().lower()
    log_text = _arg_value("--log-path")
    log_path = Path(log_text) if log_text else None
    parent_pid_text = _arg_value("--parent-pid")
    parent_pid = int(parent_pid_text) if parent_pid_text.isdigit() else 0
    source = Path(sys.executable).resolve()

    try:
        _write_update_log(log_path, f"Native helper started. source={source} target={target}")
        if expected_sha256:
            actual = _sha256_path(source)
            if actual != expected_sha256:
                raise RuntimeError(f"hash mismatch expected={expected_sha256} actual={actual}")
        _wait_for_process_exit(parent_pid, log_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        _write_update_log(log_path, "Executable replaced.")
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            str(target),
            "",
            str(target.parent),
            1,
        )
        if int(result) <= 32:
            raise RuntimeError(f"restart failed ShellExecuteW={int(result)}")
        _write_update_log(log_path, "Cloudview restarted.")
        return 0
    except Exception as exc:
        _write_update_log(log_path, f"ERROR: {exc}")
        return 1


def main() -> int:
    if "--apply-cloudview-update" in sys.argv:
        return _apply_cloudview_update_from_download()

    start_pyinstaller_parent_watchdog()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CloudviewCenter")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Cloudview Center")
    app.setApplicationDisplayName("Cloudview Center")
    app.setQuitOnLastWindowClosed(True)

    load_app_font()

    icon_path = _cloudview_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = CloudviewCenterWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
