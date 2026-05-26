from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase

from shared.constants.paths import runtime_paths


@lru_cache(maxsize=1)
def load_app_font() -> str | None:
    font_path = runtime_paths().fonts_dir / "Mabinogi_Classic_TTF.ttf"
    if not font_path.exists():
        return None
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else None


def build_font(point_size: int, weight: int | QFont.Weight = QFont.Weight.Normal) -> QFont:
    family = load_app_font()
    font = QFont()
    if family:
        font.setFamily(family)
    font.setPointSize(point_size)
    if isinstance(weight, QFont.Weight):
        font.setWeight(weight)
    else:
        normalized = min(max(int(weight), 1), 1000)
        font.setWeight(QFont.Weight(normalized))
    return font
