from __future__ import annotations

CHANNEL_TAG_ORDER = ("squad", "hq", "atc", "general")
CHANNEL_KEY_BY_TAG = {
    "squad": "ch1",
    "hq": "ch2",
    "atc": "ch3",
    "general": "ch4",
}
CHANNEL_DISPLAY_NAMES = {
    "squad": "Squad",
    "hq": "HQ",
    "atc": "ATC/SHIP",
    "general": "General",
}
CHANNEL_LIMITS = {
    "squad": 10,
    "hq": 5,
    "atc": 5,
    "general": 1,
}
DEFAULT_CHANNEL_ASSIGNMENTS = [0, 0, 0, 0]


def clamp_channel_assignment(channel_tag: str, raw_value: object) -> int:
    default_index = CHANNEL_TAG_ORDER.index(channel_tag)
    default_value = DEFAULT_CHANNEL_ASSIGNMENTS[default_index]
    limit = CHANNEL_LIMITS[channel_tag]
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default_value
    return max(0, min(limit, value))


def normalize_channel_assignments(values: list[object] | tuple[object, ...] | None) -> list[int]:
    result: list[int] = []
    for index, channel_tag in enumerate(CHANNEL_TAG_ORDER):
        raw_value = None if values is None or index >= len(values) else values[index]
        result.append(clamp_channel_assignment(channel_tag, raw_value))
    return result


def channel_assignment_for_tag(assignments: list[int], channel_tag: str) -> int:
    normalized_tag = channel_tag.strip().lower()
    try:
        index = CHANNEL_TAG_ORDER.index(normalized_tag)
    except ValueError:
        return 0
    if index >= len(assignments):
        return 0
    return clamp_channel_assignment(normalized_tag, assignments[index])
