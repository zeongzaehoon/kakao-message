# Kakao Friend Sender

카카오톡 채팅방을 선택해 글·사진을 순차 전송하는 **Rust 네이티브 macOS 앱**입니다.

- 카카오톡 스타일의 다크 사이드바·채팅 목록·노란 말풍선 미리보기를 제공합니다.
- 화면은 egui/eframe, 목록 조회·전송·저장도 Rust로 구현합니다. Python·Qt 실행기가 필요하지 않습니다.
- 10,000개 목록을 고려해 화면에 보이는 행만 그리고, 검색·선택은 메모리에서 처리합니다.
- 접근성 `AXRows`를 256개씩 읽고 방 제목만 조회합니다. 전체 목록을 주기적으로 다시 읽지 않습니다.
- 조회한 방 객체를 같은 작업 스레드에 보관합니다. 전송 때 세션 키로 바로 참조하며 전체 목록 재조회·이름 대체 검색을 하지 않습니다.
- 큰 사진은 원본을 보존하고 전송용 PNG를 20 MB 이하로 자동 조정합니다.
- 글·사진 미리보기, 대상 확인, 진행 내역, 작성 화면 복귀, CSV 저장을 지원합니다.
- 중복 이름·기존 초안·대상 변경·불확실한 전송은 중단합니다. 전송 동작을 자동 재시도하지 않습니다.
- 글·사진 전송 완료를 확인한 창만 닫고 다음 방으로 이동합니다.

## 설치·사용

[macOS DMG 다운로드 · v0.2.7](https://github.com/zeongzaehoon/kakao-message/releases/download/v0.2.7/Kakao-Friend-Sender-0.2.7-macos-arm64.dmg) · [릴리스 안내](https://github.com/zeongzaehoon/kakao-message/releases/tag/v0.2.7) · [이전 버전](https://github.com/zeongzaehoon/kakao-message/releases)

개발용 프리릴리스입니다. 릴리스의 **Assets**에서도 DMG를 받을 수 있으며, `Source code (zip)`은 설치 파일이 아닙니다. DMG와 `SHA256SUMS.txt`를 같은 폴더에 받고 `shasum -a 256 -c SHA256SUMS.txt`로 무결성을 확인할 수 있습니다.

1. Apple Silicon Mac, macOS 14.4 이상에서 DMG를 열고 안의 앱을 더블클릭합니다. **설치 / 업데이트**를 누르면 `/Applications/Kakao Friend Sender.app`에 설치하고 실행합니다.
2. 카카오톡에 로그인하고 메인 창의 **채팅 탭**을 엽니다.
3. 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용에서 이 앱을 허용합니다.
4. 새로고침 → 대화방 선택 → 글·사진 작성 → 대상 확인을 진행합니다.
5. 실제 전송을 켜고 미리보기에서 대상·내용을 확인한 뒤 전송합니다.

개발용 ad-hoc 서명이며 공증하지 않았습니다. 실행 파일 교체 후 접근성 권한 재등록이 필요할 수 있습니다. 작성 중인 글·사진은 메모리에만 있으므로 앱을 종료하기 전에 보관하세요.

기존 앱이 실행 중이면 종료 안내가 나옵니다. 작성 내용을 보관하고 기존 앱을 종료한 뒤 **다시 확인**을 누르세요. 설정·전송 이력은 유지하며, 복사·서명 검사 후 앱만 교체합니다. 교체 또는 실행 요청 실패 시 이전 앱을 복구합니다. 더 최신 버전은 덮어쓰지 않습니다. 응용 프로그램 폴더에 쓰기 권한이 필요하며, 네트워크 자동 업데이트는 하지 않습니다.

## 개발·빌드

Rust stable(1.88 이상), Xcode Command Line Tools가 필요합니다. APP·DMG 패키징에는 Node.js/npm과 Tauri CLI도 사용합니다. 앱 실행에는 Node.js·Python 설치가 필요하지 않습니다.

```bash
cargo run --manifest-path src-tauri/Cargo.toml
```

| 명령 | 용도 |
|---|---|
| `cargo test --locked --manifest-path src-tauri/Cargo.toml` | 실제 전송 없는 Rust 검사 |
| `cargo clippy --locked --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings` | 정적 검사 |
| `cargo fmt --manifest-path src-tauri/Cargo.toml --check` | 코드 형식 검사 |
| `npm ci` | 고정된 패키징 도구 설치 |
| `npm run desktop:build` | Rust APP·DMG 빌드 |
| `scripts\build_windows.bat` | Windows MSVC에서 검사·EXE 빌드 |

Mac 빌드는 서명·자체 검사·화면·DMG를 검증하고 `dist/releases/<버전>/`에 설치 파일·체크섬을 보관합니다. 중간 `.app`과 DMG 사본은 제거해 앱 목록에 중복으로 남기지 않습니다. 실행 가능한 설치본은 `/Applications/Kakao Friend Sender.app` 하나로 유지합니다. 설치 파일은 Git에서 제외하고 GitHub Releases에 첨부합니다.

## 확인 명령

```bash
src-tauri/target/release/kakao-friend-sender --self-test /tmp/kakao-self-test.json
src-tauri/target/release/kakao-friend-sender --ui-self-test /tmp/kakao-ui-self-test.json
src-tauri/target/release/kakao-friend-sender --chat-list-check /tmp/chat-list-private.json
src-tauri/target/release/kakao-friend-sender --identity-check /tmp/kakao-identity-check.json
src-tauri/target/release/kakao-friend-sender --installation-info
```

- `--self-test`: 가상 10,000개 목록·100개 대상·중복 방지를 검사합니다. 실제 전송하지 않습니다.
- `--ui-self-test FILE [화면] [compact]`: 가상 목록을 렌더링하고 JSON·PNG를 저장한 뒤 종료합니다. 화면은 `composer`, `search`, `history`, `settings`, `empty`, `confirm`이며 카카오톡에 접근하지 않습니다.
- `--chat-list-check`: 실제 채팅 목록만 읽습니다. 개별 방을 열거나 입력·전송하지 않습니다. 결과에는 대화방 이름이 있으므로 공개하지 마세요.
- `--identity-check`: 방 객체·셀의 ID 후보 속성, 본인 방 제목 일치 여부, 열린 창의 입력창·버튼 구조를 읽습니다. 이름·속성값을 저장하거나 입력·전송하지 않습니다. 고유 ID라고 판정하는 검사는 아닙니다.
- `--self-chat-test 본인이름 결과파일`: **본인 방에 테스트 글·사진을 실제 전송**하고 창 닫기까지 검사합니다. 지정한 이름의 본인 방이 유일할 때만 시작하며 기존 이력·초안 보호를 유지합니다. 실패 시 자동 재시도하지 않습니다.
- `--installation-info`: macOS 설치 위치·버전·DMG 실행 여부를 출력합니다. 앱을 교체하거나 실행하지 않습니다.

자동 검사 52개와 앱 서명·DMG·화면 검사를 통과했습니다. 실기기에서는 본인 방 진입까지 확인했으며, 기존 초안이 감지돼 글·사진 전송 완료 검증은 중단된 상태입니다. 설치·업데이트 검사는 임시 폴더에서 신규 설치, 기존 앱 교체, 실패 복구, 동시 설치 차단을 확인합니다.

## 지원 범위·제한

- macOS 전송은 KakaoTalk 26.9.0에서 관측한 접근성 구조를 사용합니다. 공식 카카오 API·AI·OCR·고정 좌표를 사용하지 않습니다.
- Windows는 Rust 화면 빌드만 지원합니다. 카카오톡 연동·전송과 실제 Windows 빌드 실행은 미검증입니다.
- JPG·PNG·WEBP·BMP, 최대 10장·전송용 PNG 한 장 20 MB·합계 60 MB입니다. 초과하면 비율을 유지해 축소합니다. 원본은 최대 128 MB·6,400만 화소이며 처리 시 2,400만 화소 이하로 줄입니다. 움직이는 사진은 지원하지 않습니다.
- 접근성에 노출된 목록만 읽으므로 숨김·보관 방을 포함한 계정 전체를 보장하지 않습니다. 전체 수를 확인하지 못하면 전송하지 않습니다.
- 전송 완료는 입력창·사진 확인창의 상태로 판단합니다. 서버 수신·상대 수신·읽음을 보장하지 않습니다.
- 전송 이력은 기존 `~/Library/Application Support/KakaoFriendSender/attempts.sqlite3`를 그대로 사용합니다. 기존 텍스트·사진 이력 키 형식도 유지합니다.
- 프로세스·화면 요소 재생성, 사진 인코딩 변경을 넘는 영구 중복 방지는 보장하지 않습니다. 결과가 불확실하면 카카오톡에서 확인하세요.
- 기존 `profile-darwin.json`의 입력창·전송 버튼 설정을 읽습니다. 메인 목록 구조는 현재 관측된 구조를 사용합니다.
- 대화창은 고정된 창 식별 번호 대신 선택한 행·제목·입력창·전송 버튼으로 확인한 뒤 해당 창 객체를 유지합니다. 본인 방의 표시용 접두어는 다른 방과 제목이 겹치지 않을 때만 허용합니다.
- 선택은 순번이 아닌 세션 키로 저장하며, 같은 객체·이름을 유지한 순서 변경은 허용합니다. 객체 교체·이름 변경·카카오톡 재시작 시 재조회·재선택이 필요합니다.
- 세션 키는 카카오톡의 영구 ID가 아닙니다. 접근성 객체가 같은 이름의 다른 방으로 재사용되는 경우까지 구분할 영구 식별자는 아직 확보하지 못했습니다.
- Rust 버전의 실제 글·사진 전송과 대량 클라이언트의 소요 시간은 실기기 검증이 필요합니다. 모의 검사 시간을 실제 전송 시간으로 보지 않습니다.

## 디렉터리

- `src-tauri/src/` — Rust 화면, 접근성, 전송, 사진, SQLite, 자체 검사.
- `src-tauri/` — Cargo 의존성·잠금 파일, 앱 아이콘, Tauri 배포 설정.
- `scripts/` — Mac 검증·패키징·중간 앱 정리와 Windows Rust 빌드 진입점.
- `.github/workflows/` — 수동 Windows 빌드. 푸시만으로 실행되지 않습니다.
- `dist/` — Git에서 제외한 설치 파일·체크섬·이전 소스 백업.

문서는 이 README로 통합합니다. 개인 진단·설정·전송 이력·캡처·빌드 산출물은 저장소에 올리지 않습니다.
