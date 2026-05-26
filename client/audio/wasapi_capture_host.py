from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from client.audio.device_registry import resolve_audio_device
from client.models.audio import AudioDeviceInfo
from shared.constants.paths import runtime_paths


FrameHandler = Callable[[bytes], Awaitable[None] | None]
LevelHandler = Callable[[float], None]


class WasapiCaptureHostProcess:
    def __init__(self, sample_rate: int = 48_000, block_size: int = 960) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device_index: int | None = None
        self.device_name = ""
        self.device_endpoint_id = ""
        self._resolved_device: AudioDeviceInfo | None = None
        self._frame_handler: FrameHandler | None = None
        self._level_handler: LevelHandler | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready_future: asyncio.Future[None] | None = None
        self.running = False
        self.last_error = ""
        self.active_device_index: int | None = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""

    def configure(
        self,
        *,
        device_index: int | None,
        device_name: str,
        device_endpoint_id: str,
        frame_handler: FrameHandler | None,
        level_handler: LevelHandler | None,
    ) -> None:
        self.device_index = device_index
        self.device_name = device_name.strip()
        self.device_endpoint_id = device_endpoint_id.strip()
        self._resolved_device = resolve_audio_device(
            "input",
            preferred_endpoint_id=self.device_endpoint_id,
            preferred_name=self.device_name,
            preferred_index=self.device_index,
        )
        self._frame_handler = frame_handler
        self._level_handler = level_handler

    def available(self) -> bool:
        return self._executable_path() is not None and sys.platform == "win32"

    async def start(self) -> None:
        executable = self._executable_path()
        if executable is None:
            raise RuntimeError("wasapi_capture_host_unavailable")

        loop = asyncio.get_running_loop()
        self._ready_future = loop.create_future()
        self.last_error = ""
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = await asyncio.create_subprocess_exec(
            *self._command_args(executable),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        try:
            await asyncio.wait_for(self._ready_future, timeout=3.0)
        except Exception:
            await self.stop()
            raise RuntimeError(self.last_error or "wasapi_capture_host_start_failed")
        self.running = True

    async def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            stdin = process.stdin
            if stdin is not None:
                with contextlib.suppress(Exception):
                    stdin.write(b'{"command":"stop"}\n')
                    await stdin.drain()
                with contextlib.suppress(Exception):
                    stdin.close()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=1.0)
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=1.0)
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=1.0)

        for task in (self._stdout_task, self._stderr_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._stdout_task = None
        self._stderr_task = None
        self._ready_future = None
        self.running = False
        self.active_device_index = None
        self.active_device_name = "default"
        self.active_device_endpoint_id = ""
        self.active_host_api_name = ""

    def _command_args(self, executable: Path) -> list[str]:
        args = [
            str(executable),
            "--mode",
            "capture",
            "--sample-rate",
            str(self.sample_rate),
            "--frame-size",
            str(self.block_size),
        ]
        endpoint_id = self._preferred_endpoint_id()
        if endpoint_id:
            args.extend(["--endpoint-id", endpoint_id])
        return args

    def _preferred_endpoint_id(self) -> str:
        if self._resolved_device is not None and self._resolved_device.endpoint_id:
            return self._resolved_device.endpoint_id
        return self.device_endpoint_id

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            raw_line = line.decode("utf-8", errors="replace").strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                self.last_error = f"invalid sidecar json: {raw_line}"
                continue
            await self._handle_payload(payload)
        if self._ready_future is not None and not self._ready_future.done():
            self._ready_future.set_exception(RuntimeError(self.last_error or "wasapi_capture_host_exited"))

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self.last_error = text

    async def _handle_payload(self, payload: dict[str, object]) -> None:
        event_name = str(payload.get("event", "")).strip().lower()
        if event_name == "ready":
            self._apply_ready_payload(payload)
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_result(None)
            return
        if event_name == "level":
            self._emit_level(payload)
            return
        if event_name == "frame":
            await self._emit_frame(payload)
            return
        if event_name in {"error", "fatal"}:
            self.last_error = str(payload.get("message", "")).strip() or event_name
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_exception(RuntimeError(self.last_error))

    def _apply_ready_payload(self, payload: dict[str, object]) -> None:
        self.active_device_index = self._resolved_device.index if self._resolved_device is not None else self.device_index
        self.active_device_name = str(payload.get("device_name", "")).strip() or (
            self._resolved_device.name if self._resolved_device is not None else self.device_name or "default"
        )
        self.active_device_endpoint_id = str(payload.get("device_id", "")).strip() or self._preferred_endpoint_id()
        self.active_host_api_name = "Windows WASAPI"

    def _emit_level(self, payload: dict[str, object]) -> None:
        if self._level_handler is None:
            return
        try:
            value = float(payload.get("value", 0.0))
        except (TypeError, ValueError):
            return
        self._level_handler(max(0.0, min(1.0, value)))

    async def _emit_frame(self, payload: dict[str, object]) -> None:
        if self._frame_handler is None:
            return
        encoded = str(payload.get("pcm_base64", "")).strip()
        if not encoded:
            return
        try:
            pcm_bytes = base64.b64decode(encoded)
        except Exception:
            return
        result = self._frame_handler(pcm_bytes)
        if asyncio.iscoroutine(result):
            await result

    def _executable_path(self) -> Path | None:
        candidates = [
            runtime_paths().bin_dir / "MaydayAudioHost.exe",
            runtime_paths().assets_dir / "bin" / "MaydayAudioHost.exe",
        ]
        native_dir = runtime_paths().root_dir / "native" / "MaydayAudioHost" / "bin"
        if native_dir.exists():
            candidates.extend(sorted(native_dir.glob("*/*/MaydayAudioHost.exe")))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None
