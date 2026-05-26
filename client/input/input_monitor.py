from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable

from client.input.bindings import MODIFIER_TOKENS, parse_binding


def _safe_import_keyboard_mouse():
    try:
        from pynput import keyboard, mouse  # type: ignore
    except Exception:
        return None, None
    return keyboard, mouse


def _safe_import_pygame():
    try:
        import pygame  # type: ignore
    except Exception:
        return None
    return pygame


class InputMonitor:
    def __init__(self) -> None:
        self._tokens: set[str] = set()
        self._lock = threading.Lock()
        self._keyboard_listener = None
        self._mouse_listener = None
        self._joystick_thread: threading.Thread | None = None
        self._joystick_start_timer: threading.Timer | None = None
        self._joystick_enabled = False
        self._joystick_stop = threading.Event()
        self._started = False
        self._callbacks: list[Callable[[set[str]], None]] = []

    def on_tokens_changed(self, callback: Callable[[set[str]], None]) -> None:
        self._callbacks.append(callback)

    @property
    def joystick_enabled(self) -> bool:
        return self._joystick_enabled

    def start(self, *, enable_joystick: bool = False) -> None:
        if self._started:
            return
        self._started = True
        keyboard_module, mouse_module = _safe_import_keyboard_mouse()
        if keyboard_module is not None:
            self._keyboard_listener = keyboard_module.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
            self._keyboard_listener.start()
        if mouse_module is not None:
            self._mouse_listener = mouse_module.Listener(
                on_click=self._on_mouse_click,
            )
            self._mouse_listener.start()
        self.set_joystick_enabled(enable_joystick, delay_seconds=1.0)

    def stop(self) -> None:
        self._started = False
        self.set_joystick_enabled(False)
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            with contextlib.suppress(Exception):
                self._keyboard_listener.join(timeout=2)
            self._keyboard_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            with contextlib.suppress(Exception):
                self._mouse_listener.join(timeout=2)
            self._mouse_listener = None

    def set_joystick_enabled(self, enabled: bool, *, delay_seconds: float = 0.0) -> None:
        self._joystick_enabled = bool(enabled)
        if self._joystick_start_timer is not None:
            self._joystick_start_timer.cancel()
            self._joystick_start_timer = None
        if not enabled:
            self._stop_joystick_thread()
            self._replace_joystick_tokens(set())
            return
        if not self._started or self._joystick_thread is not None:
            return
        if delay_seconds > 0:
            self._joystick_start_timer = threading.Timer(delay_seconds, self._start_joystick_thread)
            self._joystick_start_timer.daemon = True
            self._joystick_start_timer.start()
            return
        self._start_joystick_thread()

    def _start_joystick_thread(self) -> None:
        self._joystick_start_timer = None
        if not self._started or not self._joystick_enabled or self._joystick_thread is not None:
            return
        self._joystick_stop.clear()
        self._joystick_thread = threading.Thread(target=self._joystick_loop, daemon=True, name="mayday-joystick-monitor")
        self._joystick_thread.start()

    def _stop_joystick_thread(self) -> None:
        self._joystick_stop.set()
        if self._joystick_thread is not None:
            self._joystick_thread.join(timeout=2)
            self._joystick_thread = None

    def snapshot(self) -> set[str]:
        with self._lock:
            return set(self._tokens)

    def is_binding_pressed(self, binding: str) -> bool:
        parts = parse_binding(binding)
        tokens = self.snapshot()
        if not parts.primaries:
            return False
        if any(modifier not in tokens for modifier in parts.modifiers):
            return False
        return all(primary in tokens for primary in parts.primaries)

    def current_binding(self) -> str:
        tokens = self.snapshot()
        modifiers = [token for token in ("CTRL", "ALT", "SHIFT") if token in tokens]
        primaries = sorted(
            token
            for token in tokens
            if token not in MODIFIER_TOKENS and token and token != "+"
        )
        return "+".join([*modifiers, *primaries])

    def _on_key_press(self, key) -> None:  # noqa: ANN001
        token = self._normalize_key(key)
        if token:
            self._set_token(token, True)

    def _on_key_release(self, key) -> None:  # noqa: ANN001
        token = self._normalize_key(key)
        if token:
            self._set_token(token, False)

    def _on_mouse_click(self, x, y, button, pressed) -> None:  # noqa: ANN001
        del x, y
        token_map = {
            "Button.right": "MOUSE2",
            "Button.middle": "MOUSE3",
            "Button.x1": "MOUSE4",
            "Button.x2": "MOUSE5",
        }
        token = token_map.get(str(button))
        if token:
            self._set_token(token, pressed)

    def _normalize_key(self, key) -> str | None:  # noqa: ANN001
        name = getattr(key, "name", None)
        if name:
            normalized_name = str(name).lower()
            special = {
                "ctrl": "CTRL",
                "ctrl_l": "CTRL",
                "ctrl_r": "CTRL",
                "alt": "ALT",
                "alt_l": "ALT",
                "alt_gr": "ALT",
                "alt_r": "ALT",
                "shift": "SHIFT",
                "shift_l": "SHIFT",
                "shift_r": "SHIFT",
                "caps_lock": "CAPSLOCK",
                "space": "SPACE",
                "tab": "TAB",
                "enter": "ENTER",
                "num_pad0": "NUMPAD0",
                "num_pad1": "NUMPAD1",
                "num_pad2": "NUMPAD2",
                "num_pad3": "NUMPAD3",
                "num_pad4": "NUMPAD4",
                "num_pad5": "NUMPAD5",
                "num_pad6": "NUMPAD6",
                "num_pad7": "NUMPAD7",
                "num_pad8": "NUMPAD8",
                "num_pad9": "NUMPAD9",
                "num_lock": "NUMLOCK",
            }
            if normalized_name in special:
                return special[normalized_name]
            if normalized_name.startswith("f") and normalized_name[1:].isdigit():
                return normalized_name.upper()
        vk = getattr(key, "vk", None)
        if isinstance(vk, int):
            keypad = {
                96: "NUMPAD0",
                97: "NUMPAD1",
                98: "NUMPAD2",
                99: "NUMPAD3",
                100: "NUMPAD4",
                101: "NUMPAD5",
                102: "NUMPAD6",
                103: "NUMPAD7",
                104: "NUMPAD8",
                105: "NUMPAD9",
                106: "NUMPAD_MULTIPLY",
                107: "NUMPAD_ADD",
                109: "NUMPAD_SUBTRACT",
                110: "NUMPAD_DECIMAL",
                111: "NUMPAD_DIVIDE",
            }
            if vk in keypad:
                return keypad[vk]
        char = getattr(key, "char", None)
        if char:
            normalized_char = str(char).upper().strip()
            if not normalized_char or normalized_char == "+":
                return None
            return normalized_char
        return None

    def _joystick_loop(self) -> None:
        pygame = _safe_import_pygame()
        if pygame is None:
            return
        try:
            pygame.init()
            pygame.joystick.init()
            joysticks = self._open_joysticks(pygame)
            last_refresh = time.monotonic()
            while not self._joystick_stop.is_set():
                pygame.event.pump()
                if time.monotonic() - last_refresh > 2.0:
                    joysticks = self._open_joysticks(pygame)
                    last_refresh = time.monotonic()
                active_tokens: set[str] = set()
                for index, joystick in enumerate(joysticks, start=1):
                    button_count = joystick.get_numbuttons()
                    for button_index in range(button_count):
                        if joystick.get_button(button_index):
                            active_tokens.add(f"JOY{index}_BTN{button_index + 1}")
                    for hat_index in range(joystick.get_numhats()):
                        hat_x, hat_y = joystick.get_hat(hat_index)
                        if hat_x < 0:
                            active_tokens.add(f"JOY{index}_HAT{hat_index + 1}_LEFT")
                        elif hat_x > 0:
                            active_tokens.add(f"JOY{index}_HAT{hat_index + 1}_RIGHT")
                        if hat_y < 0:
                            active_tokens.add(f"JOY{index}_HAT{hat_index + 1}_DOWN")
                        elif hat_y > 0:
                            active_tokens.add(f"JOY{index}_HAT{hat_index + 1}_UP")
                    for axis_index in range(joystick.get_numaxes()):
                        axis_value = float(joystick.get_axis(axis_index))
                        if axis_value > 0.65:
                            active_tokens.add(f"JOY{index}_AXIS{axis_index + 1}_POS")
                        elif axis_value < -0.65:
                            active_tokens.add(f"JOY{index}_AXIS{axis_index + 1}_NEG")
                self._replace_joystick_tokens(active_tokens)
                time.sleep(0.02)
        except Exception:
            return
        finally:
            try:
                pygame.joystick.quit()
                pygame.quit()
            except Exception:
                pass

    def _open_joysticks(self, pygame) -> list:  # noqa: ANN001
        joysticks = []
        for index in range(pygame.joystick.get_count()):
            try:
                joystick = pygame.joystick.Joystick(index)
                joystick.init()
                joysticks.append(joystick)
            except Exception:
                continue
        return joysticks

    def _replace_joystick_tokens(self, active_tokens: set[str]) -> None:
        with self._lock:
            self._tokens = {token for token in self._tokens if not token.startswith("JOY")} | active_tokens
            snapshot = set(self._tokens)
        self._emit(snapshot)

    def _set_token(self, token: str, pressed: bool) -> None:
        with self._lock:
            if pressed:
                self._tokens.add(token)
            else:
                self._tokens.discard(token)
            snapshot = set(self._tokens)
        self._emit(snapshot)

    def _emit(self, snapshot: set[str]) -> None:
        for callback in self._callbacks:
            callback(set(snapshot))
