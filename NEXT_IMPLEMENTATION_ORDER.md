# Next Implementation Order

## Recommended Order After Scaffold

1. Settings dialog -> settings store 연결
2. Fleet tree widget -> fleet model 바인딩
3. Python client control connection 구현
4. Python server presence/tree snapshot 실제 송수신 연결
5. Python audio runtime -> UDP relay 연결
6. TX/RX effect sound 연결
7. Overlay speaking event 연결
8. Input capture UI 연결
9. Package build script + PyInstaller 정리
10. Localhost / LAN / external 테스트 진행

## Why This Order

- 설정과 트리 연결이 먼저 되어야 클라이언트 뼈대가 실제 앱처럼 움직인다.
- control connection이 먼저 되어야 tree/presence/overlay가 의미를 가진다.
- audio는 connection 이후 붙여야 테스트가 가능하다.
- packaging은 실제 기능 연결 후 마지막에 정리하는 게 안전하다.

