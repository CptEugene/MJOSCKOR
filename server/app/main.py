from __future__ import annotations

import argparse

from server.app.runtime import run_server_headless, run_server_shell
from shared.runtime.parent_watchdog import start_pyinstaller_parent_watchdog


if __name__ == "__main__":
    start_pyinstaller_parent_watchdog()
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run_server_headless() if args.headless else run_server_shell())
