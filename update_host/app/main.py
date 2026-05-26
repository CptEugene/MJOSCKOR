from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from update_host.ui.main_window import UpdateHostWindow


def _icon_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "assets" / "cloudview" / "icons" / "ccicon.ico"


def main() -> int:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CloudviewUpdateHost")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Cloudview Update Host")
    app.setApplicationDisplayName("Cloudview Update Host")
    icon_path = _icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = UpdateHostWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
