from __future__ import annotations

import sys
import ctypes

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from client.services.font_loader import load_app_font
from client.services.runtime_context import ensure_runtime_layout
from client.services.update_guard import check_startup_update, show_update_required_dialog
from client.ui.main_window import MaydayMainWindow
from client.ui.startup_splash import StartupSplash
from shared.constants.paths import runtime_paths
from shared.runtime.parent_watchdog import start_pyinstaller_parent_watchdog


def main() -> int:
    start_pyinstaller_parent_watchdog()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Mayday")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("MAYDAY")
    app.setApplicationDisplayName("MAYDAY")
    app.setQuitOnLastWindowClosed(True)
    update_check = check_startup_update()
    if update_check.update_required:
        show_update_required_dialog(update_check)
        return 0

    icon_path = runtime_paths().icon_file
    splash_icon_path = runtime_paths().assets_dir / "icon.png"
    splash = StartupSplash(splash_icon_path if splash_icon_path.exists() else (icon_path if icon_path.exists() else None))
    splash.show()
    splash.set_progress(12, "런타임 준비 중...")

    ensure_runtime_layout()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    splash.set_progress(42, "폰트 로딩 중...")
    app_font_family = load_app_font()
    if app_font_family:
        app.setFont(QFont(app_font_family, 9))

    splash.set_progress(74, "메인 창 시작 중...")
    window = MaydayMainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    splash.set_progress(100, "준비 완료")
    window.show()
    splash.close_with_minimum_duration()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
