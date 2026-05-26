from __future__ import annotations

from dataclasses import dataclass


MODIFIER_TOKENS = {"CTRL", "ALT", "SHIFT"}


@dataclass(slots=True)
class BindingParts:
    modifiers: tuple[str, ...]
    primaries: tuple[str, ...]

    @property
    def token_count(self) -> int:
        return len(self.modifiers) + len(self.primaries)


def normalize_binding(binding: str) -> str:
    tokens = [token.strip().upper() for token in binding.split("+") if token.strip()]
    modifiers: list[str] = []
    primaries: list[str] = []
    for token in tokens:
        if token in MODIFIER_TOKENS:
            if token not in modifiers:
                modifiers.append(token)
        else:
            if token not in primaries:
                primaries.append(token)
    return "+".join([*modifiers, *primaries])


def parse_binding(binding: str) -> BindingParts:
    normalized = normalize_binding(binding)
    modifiers: list[str] = []
    primaries: list[str] = []
    for token in normalized.split("+"):
        if not token:
            continue
        if token in MODIFIER_TOKENS:
            modifiers.append(token)
        else:
            primaries.append(token)
    return BindingParts(modifiers=tuple(modifiers), primaries=tuple(primaries))


def binding_specificity(binding: str) -> int:
    parts = parse_binding(binding)
    return (len(parts.modifiers) * 100) + len(parts.primaries)


def should_replace_pending_binding(current_binding: str, captured_binding: str) -> bool:
    if not current_binding:
        return True
    return binding_specificity(captured_binding) >= binding_specificity(current_binding)

