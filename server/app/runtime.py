from __future__ import annotations

import asyncio
import contextlib
import threading
import time

from server.app.server_core import MaydayServerCore
from shared.constants.paths import runtime_paths


class ServerRuntime:
    def __init__(self) -> None:
        paths = runtime_paths()
        self.core = MaydayServerCore(
            root_dir=paths.root_dir,
            data_dir=paths.server_data_dir,
            logs_dir=paths.server_logs_dir,
        )
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="mayday-python-server", daemon=True)

    def start(self) -> None:
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self.core.start(), self._loop)
        future.result()

    def stop(self) -> None:
        future = asyncio.run_coroutine_threadsafe(self.core.stop(), self._loop)
        future.result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


def run_server_shell() -> int:
    runtime = ServerRuntime()
    try:
        runtime.start()
    except OSError as exc:
        print(_friendly_start_error(exc))
        with contextlib.suppress(EOFError):
            input("Press Enter to close...")
        return 1
    print("MAYDAY Python Server")
    print(
        "Commands: help, status, sessions, routes, tree, ips, showpass, setpass <password>, "
        "showname, setname <server name>, showversion, setversion <version>, stop"
    )

    while True:
        command = input("> ").strip()
        lowered = command.lower()
        if lowered in {"stop", "exit", "quit"}:
            runtime.stop()
            return 0
        if lowered == "help":
            print(
                "Commands: help, status, sessions, routes, tree, ips, showpass, setpass <password>, "
                "showname, setname <server name>, showversion, setversion <version>, stop"
            )
            continue
        if lowered == "status":
            for line in runtime.core.status_lines():
                print(line)
            continue
        if lowered == "sessions":
            for line in runtime.core.session_lines():
                print(line)
            continue
        if lowered == "routes":
            for line in runtime.core.route_lines():
                print(line)
            continue
        if lowered == "tree":
            print(runtime.core.tree_text)
            continue
        if lowered == "ips":
            ips = runtime.core.local_ip_endpoints()
            print(", ".join(ips) if ips else "No IPv4 addresses found")
            continue
        if lowered == "showpass":
            print(runtime.core.server_password or "(empty)")
            continue
        if lowered.startswith("setpass "):
            runtime.core.set_password(command[8:].strip())
            continue
        if lowered == "showname":
            print(runtime.core.server_name or "MAYDAY Server")
            continue
        if lowered.startswith("setname "):
            runtime.core.set_server_name(command[8:].strip())
            continue
        if lowered == "showversion":
            print(runtime.core.minimum_client_version or "(empty)")
            continue
        if lowered.startswith("setversion "):
            runtime.core.set_minimum_client_version(command[11:].strip())
            continue
        if lowered:
            print(f"Unknown command: {command}")


def run_server_headless() -> int:
    runtime = ServerRuntime()
    try:
        runtime.start()
    except OSError as exc:
        print(_friendly_start_error(exc))
        return 1
    print("MAYDAY Python Server (headless)")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        runtime.stop()
        return 0


def _friendly_start_error(exc: OSError) -> str:
    if getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) == 10048:
        return (
            "MAYDAY Server is already running or port 41000/41001 is in use.\n"
            "Close the existing MaydayServer.exe process before starting another server."
        )
    return f"MAYDAY Server failed to start: {exc}"
