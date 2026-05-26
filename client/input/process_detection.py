from __future__ import annotations

import subprocess
import threading


STAR_CITIZEN_PROCESSES = {
    "starcitizen.exe",
    "live.exe",
}


def is_star_citizen_running() -> bool:
    try:
        startupinfo = None
        creationflags = 0
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            ["tasklist"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except Exception:
        return False

    output = completed.stdout.lower()
    return any(name in output for name in STAR_CITIZEN_PROCESSES)


class ProcessDetectionMonitor:
    def __init__(self, interval_seconds: float = 2.0) -> None:
        self._interval_seconds = interval_seconds
        self._detected = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def detected(self) -> bool:
        return self._detected

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mayday-process-detection")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._detected = is_star_citizen_running()
            self._stop.wait(self._interval_seconds)
