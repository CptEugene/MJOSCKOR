from __future__ import annotations

import warnings
from dataclasses import dataclass
import re
import threading

from client.models.audio import AudioDeviceInfo


@dataclass(slots=True, frozen=True)
class _EndpointInfo:
    endpoint_id: str
    friendly_name: str


_CACHE_LOCK = threading.Lock()
_RESOLVED_DEVICE_CACHE: dict[str, tuple[tuple[object, object], list[AudioDeviceInfo]]] = {}
_SOUNDDEVICE_CANDIDATE_CACHE: dict[str, tuple[object, dict[str, AudioDeviceInfo]]] = {}


def clear_audio_device_cache() -> None:
    with _CACHE_LOCK:
        _RESOLVED_DEVICE_CACHE.clear()
        _SOUNDDEVICE_CANDIDATE_CACHE.clear()


def _safe_import_sounddevice():
    try:
        import sounddevice as sd  # type: ignore
    except Exception:
        return None
    return sd


def _safe_import_pycaw():
    try:
        from pycaw.pycaw import AudioUtilities  # type: ignore
    except Exception:
        return None
    return AudioUtilities


def _normalize_name(raw_name: str) -> str:
    name = raw_name.strip()
    if "[" in name:
        name = name.split("[", 1)[0].strip()
    name = name.replace("(", " (").replace(")", ") ")
    name = " ".join(name.split())
    return name.strip().lower()


def _name_tokens(raw_name: str) -> set[str]:
    normalized = _normalize_name(raw_name)
    token_text = re.sub(r"[^a-z0-9]+", " ", normalized)
    return {token for token in token_text.split() if len(token) >= 3}


def _device_caps(direction: str, candidate: AudioDeviceInfo | None) -> tuple[int, int, float, str, int]:
    if candidate is None:
        if direction == "input":
            return 1, 0, 48_000.0, "Windows WASAPI", -1
        return 0, 2, 48_000.0, "Windows WASAPI", -1
    return (
        candidate.max_input_channels,
        candidate.max_output_channels,
        candidate.default_sample_rate,
        candidate.host_api_name,
        candidate.index,
    )


def _host_rank(host_api_name: str) -> int:
    priority = {
        "Windows WASAPI": 0,
        "Windows WDM-KS": 1,
        "Windows DirectSound": 2,
        "MME": 3,
    }
    return priority.get(host_api_name, 99)


def _build_sounddevice_candidates(direction: str) -> dict[str, AudioDeviceInfo]:
    sd = _safe_import_sounddevice()
    if sd is None:
        return {}

    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    best: dict[str, tuple[tuple[int, int], AudioDeviceInfo]] = {}

    for index, item in enumerate(devices):
        max_input = int(item.get("max_input_channels", 0))
        max_output = int(item.get("max_output_channels", 0))
        if direction == "input" and max_input <= 0:
            continue
        if direction == "output" and max_output <= 0:
            continue

        raw_name = str(item.get("name", f"Device {index}"))
        normalized = _normalize_name(raw_name)
        if not normalized:
            continue

        host_index = int(item.get("hostapi", -1))
        host_name = ""
        if 0 <= host_index < len(host_apis):
            host_name = str(host_apis[host_index].get("name", ""))

        info = AudioDeviceInfo(
            index=index,
            name=raw_name.split("[", 1)[0].strip(),
            max_input_channels=max_input,
            max_output_channels=max_output,
            default_sample_rate=float(item.get("default_samplerate", 48000.0)),
            host_api_name=host_name,
        )
        rank = (_host_rank(host_name), index)
        current = best.get(normalized)
        if current is None or rank < current[0]:
            best[normalized] = (rank, info)

    return {key: value[1] for key, value in best.items()}


def _find_sounddevice_candidate(endpoint_name: str, candidates: dict[str, AudioDeviceInfo]) -> AudioDeviceInfo | None:
    normalized = _normalize_name(endpoint_name)
    candidate = candidates.get(normalized)
    if candidate is not None:
        return candidate

    endpoint_tokens = _name_tokens(endpoint_name)
    if not endpoint_tokens:
        return None

    best_score = 0
    best_candidate: AudioDeviceInfo | None = None
    for candidate_name, current in candidates.items():
        candidate_tokens = _name_tokens(candidate_name)
        if not candidate_tokens:
            continue
        common = endpoint_tokens & candidate_tokens
        score = len(common)
        if normalized in candidate_name or candidate_name in normalized:
            score += 3
        if score > best_score:
            best_score = score
            best_candidate = current

    return best_candidate if best_score >= 2 else None


def _windows_active_endpoints(direction: str) -> list[_EndpointInfo]:
    AudioUtilities = _safe_import_pycaw()
    if AudioUtilities is None:
        return []

    endpoint_prefix = "{0.0.0." if direction == "output" else "{0.0.1."
    endpoints: list[_EndpointInfo] = []
    seen: set[str] = set()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        devices = list(AudioUtilities.GetAllDevices())

    for device in devices:
        try:
            state_name = getattr(getattr(device, "state", None), "name", "")
            device_id = str(getattr(device, "id", "") or "")
            friendly_name = str(getattr(device, "FriendlyName", "") or "").strip()
        except Exception:
            continue

        if state_name != "Active":
            continue
        if not device_id.startswith(endpoint_prefix):
            continue
        if not friendly_name:
            continue

        normalized = _normalize_name(friendly_name)
        if normalized in seen:
            continue
        seen.add(normalized)
        endpoints.append(_EndpointInfo(endpoint_id=device_id, friendly_name=friendly_name))

    return endpoints


def _resolve_devices(direction: str) -> list[AudioDeviceInfo]:
    candidates = _build_sounddevice_candidates(direction)
    resolved: list[AudioDeviceInfo] = []

    for endpoint in _windows_active_endpoints(direction):
        candidate = _find_sounddevice_candidate(endpoint.friendly_name, candidates)
        max_input_channels, max_output_channels, default_sample_rate, host_api_name, device_index = _device_caps(
            direction,
            candidate,
        )
        resolved.append(
            AudioDeviceInfo(
                index=device_index,
                name=endpoint.friendly_name,
                max_input_channels=max_input_channels,
                max_output_channels=max_output_channels,
                default_sample_rate=default_sample_rate,
                host_api_name=host_api_name,
                endpoint_id=endpoint.endpoint_id,
            )
        )

    return resolved


def _cached_sounddevice_candidates(direction: str) -> dict[str, AudioDeviceInfo]:
    signature = _build_sounddevice_candidates
    with _CACHE_LOCK:
        cached = _SOUNDDEVICE_CANDIDATE_CACHE.get(direction)
        if cached is not None and cached[0] == signature:
            return dict(cached[1])
    candidates = _build_sounddevice_candidates(direction)
    with _CACHE_LOCK:
        _SOUNDDEVICE_CANDIDATE_CACHE[direction] = (signature, dict(candidates))
    return dict(candidates)


def _cached_resolve_devices(direction: str) -> list[AudioDeviceInfo]:
    signature = (_build_sounddevice_candidates, _windows_active_endpoints)
    with _CACHE_LOCK:
        cached = _RESOLVED_DEVICE_CACHE.get(direction)
        if cached is not None and cached[0] == signature:
            return list(cached[1])
    devices = _resolve_devices(direction)
    with _CACHE_LOCK:
        _RESOLVED_DEVICE_CACHE[direction] = (signature, list(devices))
    return list(devices)


def list_audio_devices() -> tuple[list[AudioDeviceInfo], list[AudioDeviceInfo]]:
    input_devices = _cached_resolve_devices("input")
    output_devices = _cached_resolve_devices("output")
    if not input_devices:
        input_devices = list(_cached_sounddevice_candidates("input").values())
    if not output_devices:
        output_devices = list(_cached_sounddevice_candidates("output").values())
    return input_devices, output_devices


def resolve_audio_device(
    direction: str,
    *,
    preferred_endpoint_id: str = "",
    preferred_name: str = "",
    preferred_index: int | None = None,
) -> AudioDeviceInfo | None:
    if not preferred_endpoint_id and not preferred_name and preferred_index is None:
        return None

    devices = _cached_resolve_devices(direction)
    if preferred_endpoint_id:
        for device in devices:
            if device.endpoint_id == preferred_endpoint_id:
                return device

    normalized_name = _normalize_name(preferred_name)
    if normalized_name:
        for device in devices:
            if _normalize_name(device.name) == normalized_name:
                return device

    if preferred_index is not None:
        for device in devices:
            if device.index == preferred_index:
                return device

    sounddevice_candidates = _cached_sounddevice_candidates(direction)
    if normalized_name:
        candidate = sounddevice_candidates.get(normalized_name)
        if candidate is not None:
            return candidate

    if preferred_index is None:
        return None

    for candidate in sounddevice_candidates.values():
        if candidate.index == preferred_index:
            return candidate
    return None
