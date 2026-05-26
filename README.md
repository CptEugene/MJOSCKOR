# MAYDAY Python Rebuild

Python 기반으로 MAYDAY를 완전 재구축하는 작업선입니다.

## Current Scope

- Python `client / server / shared` 구조
- Control 서버와 클라이언트 연결
- Fleet tree / role slot 모델 바인딩
- Audio runtime / UDP transport 연결
- Overlay / Star Citizen 감지 연결

## Run

중요:

`python -m client.app.main` 과 `python -m server.app.main` 은 반드시 이 폴더에서 실행해야 합니다.

```powershell
cd C:\Users\sornr\Desktop\MAYDAY\New\python-mayday
```

### Client

```powershell
cd C:\Users\sornr\Desktop\MAYDAY\New\python-mayday
python -m client.app.main
```

또는

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_client.ps1
```

또는

```powershell
.\run_client.cmd
```

### Server

```powershell
cd C:\Users\sornr\Desktop\MAYDAY\New\python-mayday
python -m server.app.main
```

또는

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_server.ps1
```

또는

```powershell
.\run_server.cmd
```

### Headless Server

```powershell
cd C:\Users\sornr\Desktop\MAYDAY\New\python-mayday
python -m server.app.main --headless
```

또는

```powershell
.\run_server_headless.cmd
```

## Manual Smoke

1. 서버를 실행합니다.
2. 클라이언트를 실행합니다.
3. 설정창에서 서버 주소와 비밀번호를 입력하고 `CONNECT`를 누릅니다.
4. 플릿트리에서 슬롯을 더블클릭해 점유합니다.
5. 메인 창 포커스 상태에서 `1`, `2`, `3`, `4`로 채널 PTT를 테스트합니다.

## Layout

- `client/`: UI, audio, overlay, input, services
- `server/`: control, voice, fleet, persistence, auth
- `shared/`: protocol, constants, models
- `assets/`: fonts, sound
- `tests/`: automated tests
- `tools/`: helper scripts
