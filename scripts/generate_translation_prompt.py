#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def is_likely_untranslated(value: str) -> bool:
    if not value:
        return False
    if any(x in value for x in ("[PH]", "TBD", "WIP")):
        return False
    # Heuristic: contains English words
    return bool(re.search(r"[A-Za-z]{3,}", value))


def find_next_start(lines: list[str], start_at: int) -> int:
    for i in range(max(1, start_at), len(lines) + 1):
        line = lines[i - 1]
        if "=" not in line:
            continue
        _, value = line.split("=", 1)
        if is_likely_untranslated(value):
            return i
    return len(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate auto prompt for next translation batch")
    parser.add_argument("--file", default="UI_EN.ini", help="target ini file")
    parser.add_argument("--start-line", type=int, default=1, help="manual start line")
    parser.add_argument("--batch", type=int, default=180, help="batch size (150~200 recommended)")
    parser.add_argument("--auto-next", action="store_true", help="find next likely untranslated line")
    args = parser.parse_args()

    path = Path(args.file)
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    start = args.start_line
    if args.auto_next:
        start = find_next_start(lines, start)

    end = min(len(lines), start + max(1, args.batch) - 1)

    prompt = f"""스타시티즌 미션 번역 지침(요약 고정):\n- value만 번역, key/토큰/순서 유지\n- \\n은 문자열 그대로 유지(실제 개행 금지)\n- <EM4>...</EM4> 내부 미번역\n- 지역명/회사명/물건명/인물명 번역 금지\n- 한 번에 150~200줄 배치 번역\n\n작업 파일: {path}\n작업 범위: {start}-{end}\n\n출력 형식(배치 종료 시 반드시):\nNEXT_START_LINE: {min(len(lines), end + 1)}\nPROGRESS: {start}-{end}\n"""

    print(prompt)


if __name__ == "__main__":
    main()
