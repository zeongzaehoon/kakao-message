"""Current chat-window selectors; old friend/profile mappings are not used."""
from __future__ import annotations

PROFILE_FIELDS = {
    "chat_window": "대화 창",
    "editor": "메시지 입력창",
    "send_button": "전송 버튼",
}


def empty_profile(platform: str) -> dict:
    return {"version": 1, "platform": platform, "selectors": {key: {} for key in PROFILE_FIELDS}}
