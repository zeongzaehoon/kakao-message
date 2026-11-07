# Kakao Friend Sender

카카오톡 채팅방을 선택해 글·사진을 순차 전송하는 비공식 macOS 데스크톱 앱입니다.

- 채팅 목록을 먼저 조회하고 선택한 방만 열어 전송합니다.
- 글·사진을 함께 작성하고, 진행 내역에서 작성 화면으로 돌아갈 수 있습니다.
- 전송 전 대상·내용을 확인하며, 실제 전송은 기본 해제입니다.
- 기존 초안·중복 제목·대상 변경·불확실한 결과를 감지하면 중단합니다.
- 글·사진 전송이 모두 확인된 대화창을 닫고 다음 방으로 이동합니다.
- AI·OCR·고정 좌표 없이 macOS 접근성 API로 카카오톡을 제어합니다.

## 다운로드·사용

[GitHub Releases](https://github.com/zeongzaehoon/kakao-message/releases)에서 받습니다. 비공개 저장소이므로 접근 권한이 필요합니다.

1. **Apple Silicon Mac, macOS 14.4 이상**에서 DMG를 열고 앱을 응용 프로그램 폴더로 옮깁니다.
2. 카카오톡에 로그인하고 메인 창의 **채팅 탭**을 엽니다. 개별 대화창은 미리 열지 않아도 됩니다.
3. 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용에서 **Kakao Friend Sender**를 허용합니다.
4. 앱에서 채팅방·글·사진을 선택하고, 실제 전송을 끈 상태로 대상을 확인합니다.
5. 실제 전송을 켠 뒤 확인 화면에서 대상·내용을 검토하고 전송합니다.

Python 별도 설치는 필요하지 않습니다. 현재 개발용 ad-hoc 서명이며 공증하지 않아 macOS 보안 경고가 나올 수 있습니다. 앱 교체 후 접근성 재허용이 필요할 수 있습니다.

## 지원 범위·제한

- macOS: 채팅 목록 조회·글·사진 전송. KakaoTalk 26.9.0에서 관측한 접근성 구조를 사용합니다.
- Windows: 화면·접근성 진단용 **빌드 키트만 제공**합니다. 카카오톡 전송은 미지원이며 실제 EXE 빌드·실행은 미검증입니다.
- 사진: JPG·PNG·WEBP·BMP, 최대 10장. 메모리에서 PNG로 준비하며 서버에 업로드하지 않습니다.
- 접근성에 노출된 목록만 조회합니다. 계정의 모든 방을 보장하지 않으며 같은 제목의 방은 선택할 수 없습니다.
- 전송 완료는 입력창·첨부창의 상태로 판단합니다. 서버 수신·상대 수신·읽음을 보장하지 않습니다.
- 실패·결과 미확정 항목은 자동 재전송하지 않습니다. 창·프로세스 재생성을 넘는 영구 중복 방지는 보장하지 않습니다.
- 설정·전송 이력은 `~/Library/Application Support/KakaoFriendSender`에 저장합니다. 기존 초안은 일반 전송에서 덮어쓰지 않습니다.

## 개발 시작

macOS, Python 3.12가 필요합니다. 패키징에는 Xcode Command Line Tools·Rust stable·Node.js/npm도 필요합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/macos.txt
.venv/bin/python -m kakaosender
```

## 자주 쓰는 명령

저장소 루트에서 실행합니다.

| 명령 | 용도 |
|---|---|
| `.venv/bin/python -m kakaosender` | 소스에서 앱 실행 |
| `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` | 실제 전송 없는 자동 검사 |
| `npm ci` | 고정된 Tauri 빌드 도구 설치 |
| `npm run desktop:dev` | 내장 런타임을 재생성하고 개발 실행 |
| `npm run desktop:build` | Tauri macOS APP·DMG 빌드 |
| `cargo test --locked --manifest-path src-tauri/Cargo.toml` | Rust 실행기 검사 |
| `scripts\build_windows.bat` | Windows x64에서 의존성 설치·검사·EXE 빌드 |

Mac 결과는 `src-tauri/target/release/bundle/` 아래 `macos/`와 `dmg/`에 생성됩니다. Tauri는 배포·실행을, 포함된 Python/PySide6 런타임은 화면·전송을 담당합니다.

Windows 빌드는 **Windows x64 + Python 3.12 x64(`py` 런처 포함)**와 전체 소스가 필요합니다. ZIP을 압축 해제한 뒤 빌드 스크립트를 실행하세요. 성공하면 `dist/releases/0.1.0/`에 EXE·체크섬·자체 검사 결과가 생성됩니다. `.bat`는 단독 실행 앱이 아닙니다.

GitHub Actions의 **Build Windows executable**은 수동 실행 전용입니다. 푸시·태그·릴리스로 자동 실행하지 않으며 원격 Windows 빌드는 아직 실행하지 않았습니다.

## 진단·검증

```bash
.venv/bin/python -m kakaosender --chat-list-check /tmp/chat-list-private.json
.venv/bin/python -m kakaosender --diagnose /tmp/diagnostic-private.json
.venv/bin/python -m kakaosender --help
```

목록 검사·진단은 메시지를 보내지 않습니다. 진단 JSON에는 개인 정보가 포함될 수 있어 저장소에 올리지 않습니다. 본인 전송·초안 정리 명령은 사용자가 요청하고 본인 대상으로 확인한 경우에만 실행합니다.

Python 회귀 검사 115개와 Rust 검사 1개, Mac 동결 앱 자체 검사·서명·DMG 검증을 통과했습니다. 본인 채팅의 글·사진 수신과 창 닫기는 각각 확인했으나, 최종 빌드의 전체 흐름·여러 방 연속 전송은 실기기 검증 전입니다.

## 디렉터리 안내

- `src/kakaosender/` — Qt 화면, 순차 전송, 사진 처리, 설정·이력 저장.
- `src/kakaosender/adapters/` — 채팅 목록·창 식별, 공통 전송, OS 접근성 드라이버.
- `src-tauri/` — Rust 실행기, 번들 설정, 앱 아이콘.
- `requirements/` — macOS·Windows 빌드 의존성 및 고정 버전·해시.
- `scripts/` — 런타임 진입점과 macOS·Windows 빌드 스크립트.
- `tests/` — 모의 드라이버·Qt 화면 회귀 검사. 실제 카카오톡에 전송하지 않습니다.
- `.github/workflows/` — 수동 Windows 빌드 워크플로.

프로젝트 문서는 이 README로 통합합니다. 실행 환경·캐시·개인 진단·화면 캡처·전송 이력은 Git에서 제외하며, 배포 파일은 Releases에 첨부합니다.
