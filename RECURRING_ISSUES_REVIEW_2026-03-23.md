# Recurring Issues Review 2026-03-23

## 이번 점검에서 바로 수정한 항목

### 1. 마이크 레벨 측정 중 의도치 않은 송신 가능성

- 파일: `client/services/audio_runtime.py`
- 문제:
  - 마이크 레벨 측정을 위해 캡처가 살아 있는 상태에서 PTT를 떼더라도,
  - 프레임 핸들러가 계속 송신 경로를 탈 수 있는 구조였다.
- 수정:
  - `state.transmitting`이 `False`면 `_send_processed_frame()`이 즉시 반환하도록 변경
  - 장치 재시작 시 `meter_enabled` 상태도 반영하도록 변경

## 이번 점검에서 남겨둔 주의 항목

### 1. 마이크 레벨 측정 시작 시 전체 오디오 런타임이 같이 시작됨

- 파일: `client/ui/main_window.py`
- 설명:
  - `측정 시작` 버튼이 순수 측정만 켜는 게 아니라 `AudioRuntime.start()`를 호출해
    playback/transport까지 같이 올린다.
  - 지금은 기능상 문제는 없지만, 저사양 환경에서는 “측정 시작”이 무겁게 느껴질 수 있다.

### 2. 오버레이 이름 표시는 presence 스냅샷에 의존함

- 파일: `client/ui/main_window.py`
- 설명:
  - 오버레이는 실제 수신한 talker만 보여주도록 바꿨다.
  - 다만 callsign 문자열은 최신 `presence_entries`에서 세션 ID를 매칭해서 가져온다.
  - 드물게 수신 프레임이 먼저 오고 presence 갱신이 늦으면 이름 표시가 잠깐 비거나 지연될 수 있다.

### 3. 장치 목록은 설정창 열 때만 새로 읽음

- 파일: `client/ui/main_window.py`
- 설명:
  - 시작 랙을 줄이기 위해 장치 스캔을 설정창 오픈 시점으로 늦췄다.
  - 실행 중 장치가 바뀌면 설정창을 다시 열기 전까지는 목록이 갱신되지 않을 수 있다.

## 결론

- 이번에 가장 위험했던 재발 가능성 하나는 이미 수정 완료
- 현재 남은 항목은 “즉시 오류”보다는 “사용 중 체감 가능성” 수준
- 다음 수정 시에는 `RECURRING_ISSUES_CHECKLIST.md`를 먼저 확인하고 진행하는 것이 좋다
