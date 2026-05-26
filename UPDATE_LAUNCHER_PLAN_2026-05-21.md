# Cloudview Center Update Plan - 2026-05-21

## Goal

Create a separate launcher named `Cloudview Center` that manages MAYDAY installation, MAYDAY updates, and MJO Korean patch install/uninstall.

`Mayday.exe` should stay focused on the radio app itself. It should only check whether the installed version is allowed to run.

## Components

- `CloudviewCenter.exe`
  - Download MAYDAY.
  - Install MAYDAY.
  - Update MAYDAY.
  - Install MJO Korean patch.
  - Uninstall MJO Korean patch.
  - Manage install path.
  - Verify downloaded package hashes.
  - Backup and rollback failed updates.
  - Later, manage other MJO tools if needed.

- `Mayday.exe`
  - Run the radio client.
  - Check version at startup.
  - Block startup if the version is outdated.
  - Do not perform the update itself.

## Current Implementation Status

Implemented first Cloudview Center build:

- App entrypoint: `cloudview/app/main.py`
- Main UI: `cloudview/ui/main_window.py`
- Update/install logic: `cloudview/services/update_manager.py`
- PyInstaller spec: `tools/pyinstaller_cloudview.spec`
- Built executable: `dist/cloudview/CloudviewCenter.exe`
- Local test manifest: `dist/cloudview/sample_mayday_manifest.json`

Implemented in the first version:

- MAYDAY install path selection.
- Manifest URL or local manifest file selection.
- Current installed version check via `version.json`.
- Latest version check from manifest.
- Package download/copy.
- SHA256 verification.
- Existing install backup.
- User config/music/video preservation during update.
- Full package extraction/update.
- MAYDAY launch button.
- MJO Korean patch card placeholder with source/target path fields.
- Shared MAYDAY app version constant.
- Client package `version.json` generation.
- MAYDAY startup update check.
- Blocking close-only update notice when the installed version is below the required manifest version.
- Client `hello` now sends `client_version`.
- Server rejects outdated or missing client versions with `client_update_required`.
- Release builder creates `MAYDAY-client-<version>.zip` and `mayday_manifest.json` with SHA256.
- Cloudview Center auto-detects the MAYDAY update manifest from environment, adjacent override file, bundled update source, or local sample manifest.
- Cloudview Center silently checks installed MAYDAY on startup and switches to the MAYDAY update page when an update is required.
- Server `minimum_client_version` is configurable through `server.toml`.
- Server console supports `showversion` and `setversion <version>`.
- Version bump helper updates `pyproject.toml` and `APP_VERSION` together.
- Tests fail if `pyproject.toml` and `APP_VERSION` drift apart.
- Cloudview Update Host app serves the release folder over HTTP with START/STOP and manifest URLs.

Not implemented yet:

- Real hosted update manifest URL value.
- Build `CloudviewUpdateHost.exe`.
- Real MJO Korean patch install/delete rules.

## Required Startup Behavior

If `Mayday.exe` detects that the local client version is lower than the required version, it must show only a blocking notice and then exit.

Message:

```text
업데이트가 필요합니다.

현재 버전으로는 서버에 접속할 수 없습니다.
Cloudview Center에서 업데이트를 진행해 주세요.
```

Button:

```text
[닫기]
```

Do not show an `Open Cloudview Center` button for now. The user must manually open Cloudview Center and update.

## Safety Rule

Outdated clients must be blocked in two places:

- Client startup check:
  - `Mayday.exe` checks the app/update manifest.
  - If outdated, show the blocking notice and exit before entering the main app.

- Server connection check:
  - `MaydayServer` checks the client version during connection/HELLO.
  - If outdated, deny connection with a reason such as `client_update_required`.

This prevents old clients from connecting even if they bypass the local startup check.

## Recommended Install Layout

```text
MJO\
  Cloudview Center\
    CloudviewCenter.exe
    manifest_cache.json
    downloads\
    backups\
    mjo_patch\
  MAYDAY\
    Mayday.exe
    data\
    runtime\
```

Alternative single-folder layout:

```text
MAYDAY\
  CloudviewCenter.exe
  manifest_cache.json
  Mayday\
    Mayday.exe
    data\
    runtime\
  backups\
  downloads\
  mjo_patch\
```

Recommended choice: use the `MJO\Cloudview Center` + `MJO\MAYDAY` layout because Cloudview Center may manage more than MAYDAY later.

## Update Manifest Example

```json
{
  "product": "MAYDAY",
  "latest_version": "1.0.2",
  "minimum_required_version": "1.0.2",
  "required": true,
  "package_url": "https://example.com/mayday/client-1.0.2.zip",
  "sha256": "package_sha256_hash",
  "notes": [
    "비파일럿 음량 조정",
    "통신 시작음 조정",
    "오디오 안정화"
  ]
}
```

## Cloudview Center Update Flow

```text
CloudviewCenter.exe 실행
-> manifest 확인
-> 설치된 MAYDAY 버전 확인
-> 업데이트 필요 표시
-> [업데이트] 클릭
-> Mayday.exe 실행 중이면 종료 요청
-> 패키지 다운로드
-> SHA256 검증
-> 기존 설치 파일 백업
-> 새 파일 압축 해제
-> 업데이트 완료
-> 필요 시 MAYDAY 실행 버튼 표시
```

## MAYDAY Client Startup Flow

```text
Mayday.exe 실행
-> manifest 또는 서버 요구 버전 확인
-> 현재 버전이 낮음
-> blocking notice 표시
-> [닫기]
-> 프로그램 종료
```

## MJO Korean Patch Flow

```text
CloudviewCenter.exe 실행
-> MJO 한글패치 상태 확인
-> [한글패치 설치] 또는 [한글패치 삭제] 선택
-> 대상 게임/패치 경로 확인
-> 기존 파일 백업
-> 패치 적용 또는 복구
-> 완료 상태 표시
```

## Implementation Notes

- Use full package replacement first, not binary diff patching.
- Keep update download and extraction outside the running `Mayday.exe`.
- Verify every downloaded package with SHA256 before replacing files.
- Keep a backup before replacing files so rollback is possible.
- Store installed MAYDAY version in a small local file, for example `MAYDAY/version.json`.
- Keep protocol compatibility separate from app display version if needed later.
- Cloudview Center should be allowed to continue running even when MAYDAY is not installed.

## Future Nice-to-Have

- Stable/test update channels.
- Patch notes viewer in `CloudviewCenter.exe`.
- Repair install button.
- Clean reinstall button.
- Log export button.
- Server package update management.
- Admin-managed forced update flag.
- Multiple MJO tool cards inside Cloudview Center.
