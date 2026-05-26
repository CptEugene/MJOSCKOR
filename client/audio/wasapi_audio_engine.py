from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from client.audio.device_registry import resolve_audio_device
from client.models.audio import AudioDeviceInfo
from shared.constants.paths import runtime_paths


LevelHandler = Callable[[float], None]
TalkerHandler = Callable[[int, str, bool], None]
ErrorHandler = Callable[[str], None]


class WasapiAudioEngineProcess:
    def __init__(self) -> None:
        self.input_device_index: int | None = None
        self.input_device_name = ""
        self.input_device_endpoint_id = ""
        self.output_device_index: int | None = None
        self.output_device_name = ""
        self.output_device_endpoint_id = ""
        self.voice_host = "127.0.0.1"
        self.voice_port = 41001
        self.session_id = 0
        self.channel_tag = "general"
        self.selected_role = "Soldier"
        self.microphone_volume_percent = 100
        self.speaker_volume_percent = 100
        self.channel_receive_volumes = [100, 100, 100, 100]
        self.channel_pan_modes = ["both", "both", "both", "both"]
        self._resolved_input: AudioDeviceInfo | None = None
        self._resolved_output: AudioDeviceInfo | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready_future: asyncio.Future[None] | None = None
        self.running = False
        self.last_error = ""
        self.active_input_device_name = "default"
        self.active_input_device_endpoint_id = ""
        self.active_output_device_name = "default"
        self.active_output_device_endpoint_id = ""
        self.active_backend_name = "native-engine"
        self._level_handler: LevelHandler | None = None
        self._talker_handler: TalkerHandler | None = None
        self._error_handler: ErrorHandler | None = None

    def configure_devices(
        self,
        *,
        input_device_index: int | None,
        input_device_name: str,
        input_device_endpoint_id: str,
        output_device_index: int | None,
        output_device_name: str,
        output_device_endpoint_id: str,
    ) -> None:
        self.input_device_index = input_device_index
        self.input_device_name = input_device_name.strip()
        self.input_device_endpoint_id = input_device_endpoint_id.strip()
        self.output_device_index = output_device_index
        self.output_device_name = output_device_name.strip()
        self.output_device_endpoint_id = output_device_endpoint_id.strip()
        self._resolved_input = resolve_audio_device(
            "input",
            preferred_endpoint_id=self.input_device_endpoint_id,
            preferred_name=self.input_device_name,
            preferred_index=self.input_device_index,
        )
        self._resolved_output = resolve_audio_device(
            "output",
            preferred_endpoint_id=self.output_device_endpoint_id,
            preferred_name=self.output_device_name,
            preferred_index=self.output_device_index,
        )

    def configure_transport(self, *, host: str, port: int, session_id: int, channel_tag: str) -> None:
        self.voice_host = host.strip() or self.voice_host
        self.voice_port = port
        self.session_id = session_id
        self.channel_tag = channel_tag.strip().lower() or "general"

    def configure_role(self, selected_role: str) -> None:
        self.selected_role = selected_role.strip() or "Soldier"

    def configure_levels(
        self,
        *,
        microphone_volume_percent: int,
        speaker_volume_percent: int,
        channel_receive_volumes: list[int],
        channel_pan_modes: list[str],
    ) -> None:
        self.microphone_volume_percent = max(0, min(200, int(microphone_volume_percent)))
        self.speaker_volume_percent = max(0, min(200, int(speaker_volume_percent)))
        self.channel_receive_volumes = [max(0, min(200, int(value))) for value in channel_receive_volumes[:4]]
        while len(self.channel_receive_volumes) < 4:
            self.channel_receive_volumes.append(100)
        self.channel_pan_modes = [str(value).strip().lower() or "both" for value in channel_pan_modes[:4]]
        while len(self.channel_pan_modes) < 4:
            self.channel_pan_modes.append("both")

    def set_level_handler(self, handler: LevelHandler | None) -> None:
        self._level_handler = handler

    def set_talker_handler(self, handler: TalkerHandler | None) -> None:
        self._talker_handler = handler

    def set_error_handler(self, handler: ErrorHandler | None) -> None:
        self._error_handler = handler

    def available(self) -> bool:
        return self._executable_path() is not None and sys.platform == "win32"

    async def start(self) -> None:
        executable = self._executable_path()
        if executable is None:
            raise RuntimeError("wasapi_audio_engine_unavailable")

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
            await asyncio.wait_for(self._ready_future, timeout=4.0)
        except Exception:
            await self.stop()
            raise RuntimeError(self.last_error or "wasapi_audio_engine_start_failed")
        self.running = True
        await self._send_configure()

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

    async def set_ptt(self, pressed: bool, channel_tag: str) -> None:
        if self._process is None or self._process.stdin is None:
            return
        self.channel_tag = channel_tag.strip().lower() or self.channel_tag
        payload = {"command": "ptt", "pressed": bool(pressed), "channel_tag": self.channel_tag}
        await self._send_json(payload)

    async def sync_configuration(self) -> None:
        if not self.running:
            return
        await self._send_configure()

    async def _send_configure(self) -> None:
        payload = {
            "command": "configure",
            "voice_host": self.voice_host,
            "voice_port": self.voice_port,
            "session_id": self.session_id,
            "channel_tag": self.channel_tag,
            "selected_role": self.selected_role,
            "microphone_volume_percent": self.microphone_volume_percent,
            "speaker_volume_percent": self.speaker_volume_percent,
            "channel_receive_volumes": self.channel_receive_volumes,
            "channel_pan_modes": self.channel_pan_modes,
        }
        await self._send_json(payload)

    async def _send_json(self, payload: dict) -> None:
        if self._process is None or self._process.stdin is None:
            return
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self._process.stdin.write(encoded)
        await self._process.stdin.drain()

    def _command_args(self, executable: Path) -> list[str]:
        args = [
            str(executable),
            "--mode",
            "engine",
            "--voice-host",
            self.voice_host,
            "--voice-port",
            str(self.voice_port),
            "--session-id",
            str(self.session_id),
            "--channel-tag",
            self.channel_tag,
        ]
        input_endpoint_id = self._resolved_input.endpoint_id if self._resolved_input is not None else self.input_device_endpoint_id
        output_endpoint_id = self._resolved_output.endpoint_id if self._resolved_output is not None else self.output_device_endpoint_id
        if input_endpoint_id:
            args.extend(["--input-endpoint-id", input_endpoint_id])
        if output_endpoint_id:
            args.extend(["--output-endpoint-id", output_endpoint_id])
        return args

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
                self.last_error = f"invalid engine json: {raw_line}"
                continue
            await self._handle_payload(payload)
        unexpected_exit = self._process is process
        if unexpected_exit:
            self.running = False
        if self._ready_future is not None and not self._ready_future.done():
            self._ready_future.set_exception(RuntimeError(self.last_error or "wasapi_audio_engine_exited"))
        elif unexpected_exit:
            message = self.last_error or "native audio engine exited unexpectedly"
            self.last_error = message
            if self._error_handler is not None:
                self._error_handler(f"DIAG {message}")

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
                if self._error_handler is not None:
                    self._error_handler(text)

    async def _handle_payload(self, payload: dict[str, object]) -> None:
        event_name = str(payload.get("event", "")).strip().lower()
        if event_name == "ready":
            self.active_input_device_name = str(payload.get("capture_device_name", "")).strip() or "default"
            self.active_input_device_endpoint_id = str(payload.get("capture_device_id", "")).strip()
            self.active_output_device_name = str(payload.get("playback_device_name", "")).strip() or "default"
            self.active_output_device_endpoint_id = str(payload.get("playback_device_id", "")).strip()
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_result(None)
            return
        if event_name == "level":
            if self._level_handler is None:
                return
            try:
                value = float(payload.get("value", 0.0))
            except (TypeError, ValueError):
                return
            self._level_handler(max(0.0, min(1.0, value)))
            return
        if event_name == "talker_state":
            if self._talker_handler is None:
                return
            try:
                session_id = int(payload.get("session_id", 0))
            except (TypeError, ValueError):
                return
            channel_tag = str(payload.get("channel_tag", "")).strip().lower() or "general"
            active = bool(payload.get("active", False))
            self._talker_handler(session_id, channel_tag, active)
            return
        if event_name in {"error", "fatal"}:
            message = str(payload.get("message", "")).strip() or event_name
            self.last_error = message
            if self._error_handler is not None:
                self._error_handler(message)
            if self._ready_future is not None and not self._ready_future.done():
                self._ready_future.set_exception(RuntimeError(message))
            return
        if event_name == "diagnostic":
            message = str(payload.get("message", "")).strip()
            if message and self._error_handler is not None:
                self._error_handler(f"DIAG {message}")

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
