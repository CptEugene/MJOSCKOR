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


def build_prompt(path: Path, start: int, end: int, total: int) -> str:
    return f"""스타시티즌 미션 번역 지침(요약 고정):\n- value만 번역, key/토큰/순서 유지\n- \\n은 문자열 그대로 유지(실제 개행 금지)\n- <EM4>...</EM4> 내부 미번역\n- 지역명/회사명/물건명/인물명 번역 금지\n- 한 번에 150~200줄 배치 번역\n\n작업 파일: {path}\n작업 범위: {start}-{end}\n\n출력 형식(배치 종료 시 반드시):\nNEXT_START_LINE: {min(total, end + 1)}\nPROGRESS: {start}-{end}\n"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate auto prompt for next translation batch")
    parser.add_argument("--file", default="UI_EN.ini", help="target ini file")
    parser.add_argument("--start-line", type=int, default=1, help="manual start line")
    parser.add_argument("--batch", type=int, default=180, help="batch size (150~200 recommended)")
    parser.add_argument("--auto-next", action="store_true", help="find next likely untranslated line")
    parser.add_argument(
        "--plan-to-eof",
        action="store_true",
        help="print all batch ranges from start line to EOF (or next untranslated line)",
    )
    args = parser.parse_args()

    path = Path(args.file)
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    start = args.start_line
    if args.auto_next:
        start = find_next_start(lines, start)

    batch = max(1, args.batch)
    end = min(len(lines), start + batch - 1)

    if not args.plan_to_eof:
        print(build_prompt(path, start, end, len(lines)))
        return

    print(f"FILE: {path}")
    print(f"TOTAL_LINES: {len(lines)}")
    print(f"BATCH_SIZE: {batch}")

    cursor = start
    step = 1
    while cursor <= len(lines):
        batch_end = min(len(lines), cursor + batch - 1)
        print(f"BATCH {step}: {cursor}-{batch_end}")
        print(f"NEXT_START_LINE: {min(len(lines), batch_end + 1)}")
        print(f"PROGRESS: {cursor}-{batch_end}")
        if batch_end >= len(lines):
            break
        cursor = batch_end + 1
        step += 1


if __name__ == "__main__":
    main()
