# Translation Auto Prompt

배치 번역을 자동으로 이어가려면 아래 명령을 사용하세요.

```bash
python scripts/generate_translation_prompt.py --file UI_EN.ini --start-line 1366 --batch 180 --auto-next
```

- `--auto-next`: 시작 라인 이후에서 영어가 남아있는 다음 라인을 자동 탐색합니다.
- `--batch`: 기본 180줄이며, 150~200 범위를 권장합니다.

파일 끝까지 끊김 없이 배치 계획을 출력하려면 아래 명령을 사용하세요.

```bash
python scripts/generate_translation_prompt.py --file UI_EN.ini --start-line 1366 --batch 180 --auto-next --plan-to-eof
```

- `--plan-to-eof`: 시작 지점부터 EOF까지 모든 배치를 `BATCH n`, `NEXT_START_LINE`, `PROGRESS` 형식으로 연속 출력합니다.
- 연속 처리 시 작업자는 출력된 배치 순서대로 번역을 적용하면 되며, 중간 보고 없이 EOF까지 진행할 수 있습니다.

- 파일이 비어 있거나 잘못된 경로일 경우 즉시 오류를 출력합니다.
- `--auto-next` 사용 시 더 이상 미번역 라인이 없으면 `STATUS: no likely untranslated lines found`를 출력하고 종료합니다.
