from __future__ import annotations

from collections import Counter
from threading import Event

from .accessibility import Driver, Node, matches
from .sender import ChatSender
from ..models import Friend, FriendList, IntegrationError, WindowBinding, canonical, checkpoint, digest


class OpenChatsBackend(ChatSender):
    """Send only to an already open, explicitly selected native window."""

    def finish_recipient(self, friend: Friend, scope: str, stop: Event) -> None:
        self._check_scope(scope, stop)
        chat = self._chat(friend, stop)
        editor, _ = self._controls(friend, stop)
        if self.driver.read_value(editor) or self.driver.photo_sheets(chat):
            raise IntegrationError("작성 중인 내용이나 첨부 창이 있어 대화창을 닫지 않았습니다.")
        self.driver.close_chat(chat, stop)
        self.prepared = None
        self.closed_recipients.add(friend.key)

    def __init__(self, driver: Driver, profile: dict, expected_pid: int | None = None):
        if driver.platform != "darwin":
            raise IntegrationError("열린 대화방 연결은 현재 macOS에서만 지원합니다.")
        defaults = {
            "chat_window": {"role": "AXWindow", "identifier": "_NS:443"},
            "editor": {"role": "AXTextArea", "identifier": "_NS:51"},
            "send_button": {"role": "AXButton", "name": "전송"},
        }
        for name in defaults:
            configured = profile.get("selectors", {}).get(name)
            if configured and any(configured.values()):
                defaults[name] = dict(configured)
        # A list enumerates titles; it does not search for a person's name.
        defaults["chat_window"].pop("name", None)
        super().__init__(driver, {**profile, "selectors": defaults}, expected_pid)
        self.closed_recipients: set[str] = set()

    def _scope(self, stop: Event) -> str:
        checkpoint(stop)
        if self.expected_pid is not None and self.driver.pid != self.expected_pid:
            raise IntegrationError("카카오톡이 다시 실행되었습니다. 열린 대화방을 새로고침해 주세요.")
        return f"{self.driver.platform}:open-chats:{self.driver.pid}"

    def _windows(self, stop: Event) -> list[Node]:
        self._scope(stop)
        return [node for node in self.driver.current_roots()
                if matches(node, self.selectors["chat_window"]) and canonical(node.name)]

    def _key(self, node: Node) -> str:
        return "chat:" + digest(f"{self.driver.pid}:{node.key}:{canonical(node.name)}")

    def list_friends(self, stop: Event) -> FriendList:
        # Keep the shared recipient model; no friend-list/profile APIs are called.
        windows = self._windows(stop)
        titles = Counter(canonical(node.name) for node in windows)
        keys = Counter(node.key for node in windows)
        recipients = []
        for node in windows:
            checkpoint(stop)
            name = canonical(node.name)
            reason = ""
            if titles[name] > 1 or keys[node.key] > 1:
                reason = "같은 제목의 창 또는 구분되지 않는 창 · 선택 불가"
            else:
                try:
                    editor, button = self.driver.chat_controls(node, self.selectors, stop)
                    if not self.driver.can_write(editor) or not self.driver.can_press(button):
                        reason = "입력 또는 전송 동작 미지원"
                except IntegrationError:
                    reason = "입력창 또는 전송 버튼을 확인할 수 없음"
            recipients.append(Friend(self._key(node), name, not reason, reason or "열린 대화창",
                                     window=WindowBinding(self.driver.pid, node.key, node.native)))
        note = "카카오톡에서 대화방을 별도 창으로 열고 새로고침하세요."
        return FriendList(tuple(recipients), self._scope(stop), True, note, self.driver.pid)

    def _chat(self, friend: Friend, stop: Event) -> Node:
        self._scope(stop)
        binding = friend.window
        if binding is None or binding.pid != self.driver.pid or not friend.selectable:
            raise IntegrationError("목록에서 선택한 대화창 정보가 없습니다. 새로고침해 주세요.")
        windows = self._windows(stop)
        same_title = [node for node in windows if canonical(node.name) == friend.name]
        if len(same_title) != 1:
            raise IntegrationError("선택한 대화창이 닫혔거나 제목이 중복/변경되었습니다. 새로고침해 주세요.")
        chat = same_title[0]
        if (chat.key != binding.key or self._key(chat) != friend.key
                or not self.driver.same_element(chat.native, binding.native)):
            raise IntegrationError("선택 이후 대화창이 교체되었습니다. 새로고침해 주세요.")
        fresh = self.driver.refresh_node(chat)
        if (fresh.key != chat.key or canonical(fresh.name) != friend.name
                or not matches(fresh, self.selectors["chat_window"])):
            raise IntegrationError("대화창 정보가 변경되었습니다. 새로고침해 주세요.")
        return fresh

    def prepare(self, friend: Friend, scope: str, stop: Event) -> None:
        self.prepared = None
        self._check_scope(scope, stop)
        editor, _ = self._controls(friend, stop)
        if self.driver.read_value(editor):
            raise IntegrationError("선택한 대화창에 작성 중인 내용이 있습니다. 먼저 직접 정리해 주세요.")
        if self.driver.photo_sheets(self._chat(friend, stop)):
            raise IntegrationError("선택한 대화창에 첨부 확인 창이 있습니다. 먼저 직접 정리해 주세요.")
        self.prepared = friend.key
