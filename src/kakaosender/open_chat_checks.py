"""Read-only listing and explicit target selection for real self-chat checks."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from .adapters.open_chats import OpenChatsBackend
from .adapters.conversations import ConversationBackend
from .models import Friend, IntegrationError


def self_test_backend(driver, target_path: Path) -> OpenChatsBackend:
    target = json.loads(target_path.read_text(encoding="utf-8"))
    if str(target.get("key", "")).startswith("conversation:"):
        return ConversationBackend(driver, {})
    return OpenChatsBackend(driver, {})


def confirmed_self_target(backend: OpenChatsBackend, target_path: Path) -> tuple[Friend, str]:
    target = json.loads(target_path.read_text(encoding="utf-8"))
    if target.get("confirmed_self_chat") is not True or target.get("pid") != backend.driver.pid:
        raise IntegrationError("현재 실행 중인 카카오톡의 본인 대화창 확인이 필요합니다.")
    listing = backend.list_friends(Event())
    selected = [friend for friend in listing.friends if friend.key == target.get("key")
                and friend.name == target.get("name") and friend.selectable]
    if len(selected) != 1:
        raise IntegrationError("확인한 본인 대화창이 변경됐습니다. 열린 대화방 목록을 다시 확인해 주세요.")
    return selected[0], listing.scope


def run_open_chats_check(report: Path, from_list: bool = False) -> int:
    from .adapters import native_driver
    backend = None
    try:
        backend = (ConversationBackend if from_list else OpenChatsBackend)(native_driver(), {})
        listing = backend.list_friends(Event())
        payload = {"ok": True, "pid": listing.session_pid, "count": len(listing.friends),
                   "complete": listing.complete,
                   "rooms" if from_list else "windows": [{"key": friend.key, "name": friend.name,
                                "selectable": friend.selectable, "note": friend.note}
                               for friend in listing.friends], "sent": 0}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "sent": 0}
    finally:
        if backend is not None:
            backend.close()
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1


def run_clear_self_draft(report: Path, target_path: Path) -> int:
    """Explicit user-requested text clearing, only in a confirmed self-chat."""
    from .adapters import native_driver
    backend = None
    try:
        backend = self_test_backend(native_driver(), target_path)
        friend, scope = confirmed_self_target(backend, target_path)
        stop = Event()
        if isinstance(backend, ConversationBackend):
            backend.open_target(friend, scope, stop)
        backend._check_scope(scope, stop)
        chat = backend._chat(friend, stop)
        if backend.driver.photo_sheets(chat):
            raise IntegrationError("첨부 확인 창이 있어 텍스트 초안을 정리하지 않았습니다.")
        editor, _ = backend._controls(friend, stop)
        original = backend.driver.read_value(editor)
        current, _ = backend._controls(friend, stop)
        if not backend.driver.same_element(current.native, editor.native) or backend.driver.read_value(current) != original:
            raise IntegrationError("초안 또는 입력창이 변경돼 정리하지 않았습니다.")
        if original:
            backend.driver.set_value(current, "")
        verified, _ = backend._controls(friend, stop)
        if backend.driver.read_value(verified):
            raise IntegrationError("입력창이 비워졌는지 확인하지 못했습니다.")
        payload = {"ok": True, "cleared": bool(original), "input_empty": True}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    finally:
        if backend is not None:
            backend.close()
    payload.update(self_only=True, sent=0)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1


def run_close_self_chat(report: Path, target_path: Path) -> int:
    """Close an already open, confirmed self-chat without sending another test."""
    from .adapters import native_driver
    backend = None
    try:
        backend = OpenChatsBackend(native_driver(), {})
        friend, scope = confirmed_self_target(backend, target_path)
        backend.finish_recipient(friend, scope, Event())
        payload = {"ok": True, "chat_closed": friend.key in backend.closed_recipients}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    finally:
        if backend is not None:
            backend.close()
    payload.update(self_only=True, sent=0)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1
