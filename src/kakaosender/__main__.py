from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from threading import Event


def main():
    parser = argparse.ArgumentParser(description="Kakao Friend Sender 개발 시제품")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--diagnose", type=Path, metavar="FILE", help="접근성 진단 JSON 저장; 메시지를 전송하지 않음")
    mode.add_argument("--send-self-test", type=Path, metavar="FILE", help="현재 계정의 나와의 채팅에 고정 테스트 글과 사진을 실제 전송; JSON 결과 저장")
    mode.add_argument("--prepare-self-check", type=Path, metavar="FILE", help="본인 대화창 진입과 빈 입력창만 확인; 입력/전송 없음")
    mode.add_argument("--open-chats-check", type=Path, metavar="FILE", help="열린 대화창 제목·선택 식별자만 JSON 저장; 입력/전송 없음")
    mode.add_argument("--chat-list-check", type=Path, metavar="FILE", help="메인 채팅 탭의 대화방 목록 조회; 대화창 열기/입력/전송 없음")
    mode.add_argument("--clear-self-draft", type=Path, metavar="FILE", help="명시적으로 확인한 본인 채팅의 텍스트 초안만 비움; 전송 없음")
    mode.add_argument("--close-self-chat", type=Path, metavar="FILE", help="확인된 본인 대화창만 닫기; 초안·첨부가 있으면 중단, 전송 없음")
    parser.add_argument("--chat-target", type=Path, metavar="FILE", help="사용자가 본인 대화창으로 확인한 pid/key/name/confirmed_self_chat JSON")
    mode.add_argument("--self-test", type=Path, metavar="FILE", help="임시 저장소로 패키지 자체 검사 후 JSON 저장; 카카오톡에 연결하지 않음")
    mode.add_argument("--connection-check", type=Path, metavar="FILE", help="연동 지원 여부와 macOS 접근성 권한을 JSON으로 저장")
    args = parser.parse_args()
    if (args.prepare_self_check or args.send_self_test or args.clear_self_draft or args.close_self_chat) and not args.chat_target:
        parser.error("본인 테스트에는 --chat-target으로 확인된 본인 채팅 대상을 지정해야 합니다.")
    if args.clear_self_draft:
        from .open_chat_checks import run_clear_self_draft
        return run_clear_self_draft(args.clear_self_draft, args.chat_target)
    if args.close_self_chat:
        from .open_chat_checks import run_close_self_chat
        return run_close_self_chat(args.close_self_chat, args.chat_target)
    if args.open_chats_check or args.chat_list_check:
        from .open_chat_checks import run_open_chats_check
        return run_open_chats_check(args.open_chats_check or args.chat_list_check,
                                   from_list=bool(args.chat_list_check))
    if args.prepare_self_check:
        from .live_self_test import run_self_prepare_check
        return run_self_prepare_check(args.prepare_self_check, args.chat_target)
    if args.send_self_test:
        from .live_self_test import run_live_self_test
        return run_live_self_test(args.send_self_test, args.chat_target)
    if args.self_test:
        from .self_test import run_self_test
        return run_self_test(args.self_test)
    if args.connection_check:
        if sys.platform != "darwin":
            args.connection_check.write_text(json.dumps({
                "platform": sys.platform,
                "sending_supported": False,
                "error": "카카오톡 목록 조회와 전송은 현재 macOS에서만 지원합니다. Windows는 화면·접근성 진단만 지원합니다.",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        from .adapters.macos import connection_status
        args.connection_check.write_text(json.dumps(connection_status(), ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    if args.diagnose:
        from .adapters import native_driver
        from .models import IntegrationError
        driver = None
        try:
            driver = native_driver()
            args.diagnose.write_text(json.dumps(driver.snapshot(Event()), ensure_ascii=False, indent=2), encoding="utf-8")
        except IntegrationError as exc:
            args.diagnose.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        finally:
            if driver is not None:
                driver.close()
        print(f"진단 저장: {args.diagnose}")
        return 0
    from .ui import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
