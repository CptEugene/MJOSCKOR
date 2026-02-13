# Translation Auto Prompt

배치 번역을 자동으로 이어가려면 아래 명령을 사용하세요.

```bash
python scripts/generate_translation_prompt.py --file UI_EN.ini --start-line 1366 --batch 180 --auto-next
```

- `--auto-next`: 시작 라인 이후에서 영어가 남아있는 다음 라인을 자동 탐색합니다.
- `--batch`: 기본 180줄이며, 150~200 범위를 권장합니다.

출력된 프롬프트를 그대로 사용하면, 다음 배치의 작업 범위와 종료 시 출력할 `NEXT_START_LINE`, `PROGRESS`가 자동으로 포함됩니다.
