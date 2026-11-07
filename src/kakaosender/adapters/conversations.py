from __future__ import annotations

from collections import Counter
from threading import Event
import time

from .accessibility import Driver, Node, matches
from .open_chats import OpenChatsBackend
from ..models import (ConversationBinding, Friend, FriendList, IntegrationError,
                      WindowBinding, canonical, checkpoint, digest)


class ConversationBackend(OpenChatsBackend):
    """List the main Chats table first; open only explicitly selected rows."""

    def __init__(self, driver: Driver, profile: dict, expected_pid: int | None = None,
                 catalog: WindowBinding | None = None):
        super().__init__(driver, profile, expected_pid)
        self.catalog = catalog
        self._bound_chats: dict[str, Friend] = {}

    def _scope(self, stop: Event) -> str:
        super()._scope(stop)
        return f"{self.driver.platform}:conversations:{self.driver.pid}"

    def _catalog_main(self, stop: Event) -> Node:
        self._scope(stop)
        mains = [node for node in self.driver.current_roots()
                 if node.role == "AXWindow" and node.identifier == "Main Window"]
        if len(mains) == 1:
            main = mains[0]
        elif not mains and self.catalog is not None and self.catalog.pid == self.driver.pid:
            main = self.driver.refresh_node(Node("AXWindow", "", "Main Window", self.catalog.native, self.catalog.key))
            if main.role != "AXWindow" or main.identifier != "Main Window" or main.key != self.catalog.key:
                raise IntegrationError("카카오톡 메인 창이 변경되었습니다. 채팅 탭을 열고 새로고침해 주세요.")
        else:
            raise IntegrationError("카카오톡 메인 창의 채팅 탭을 열어 주세요. 개별 대화창은 미리 열 필요가 없습니다.")
        self.catalog = WindowBinding(self.driver.pid, main.key, main.native)
        return main

    def _catalog_rows(self, stop: Event) -> tuple[Node, Node, list[tuple[Node, str]], bool]:
        main = self._catalog_main(stop)
        try:
            area = self.driver.one({"role": "AXScrollArea", "identifier": "_NS:101"}, stop, main, roots_only=True)
            table = self.driver.one({"role": "AXTable", "identifier": "_NS:63"}, stop, area, roots_only=True)
        except IntegrationError as exc:
            raise IntegrationError("카카오톡 메인 창을 채팅 탭으로 바꿔 주세요. 친구 목록은 발송 대상으로 읽지 않습니다.") from exc
        rows = [node for node in self.driver.children(table) if node.role == "AXRow"]
        found = []
        for row in rows:
            checkpoint(stop)
            title = self.driver.one({"role": "AXStaticText", "identifier": "_NS:40"}, stop, row)
            name = canonical(title.name)
            if not name:
                raise IntegrationError("제목이 없는 채팅 행이 있어 목록을 확인하지 못했습니다.")
            found.append((row, name))
        count = self.driver.row_count(table)
        complete = count is None or count == len(rows)
        return main, table, found, complete

    def _row_key(self, row: Node, title: str) -> str:
        return "conversation:" + digest(f"{self.driver.pid}:{row.key}:{title}")

    def list_friends(self, stop: Event) -> FriendList:
        main, table, rows, complete = self._catalog_rows(stop)
        titles = Counter(name for _, name in rows)
        keys = Counter(row.key for row, _ in rows)
        recipients = []
        for row, name in rows:
            reason = ""
            if not complete:
                reason = "목록의 행 수가 일치하지 않아 전송 불가"
            elif titles[name] > 1 or keys[row.key] > 1:
                reason = "같은 제목의 채팅방 · 선택 불가"
            elif not self.driver.can_open_conversation(table, row):
                reason = "채팅 행 선택/열기 동작 미지원"
            binding = ConversationBinding(self.catalog, table.key, table.native, row.key, row.native)
            recipients.append(Friend(self._row_key(row, name), name, not reason,
                                     reason or "채팅 목록 · 전송 시 열기", conversation=binding))
        return FriendList(tuple(recipients), self._scope(stop), complete,
                          "카카오톡 접근성에 노출된 채팅 목록입니다. 숨김/보관된 방을 포함한 계정 전체 목록은 아닙니다.",
                          self.driver.pid, catalog=self.catalog)

    def _chat(self, friend: Friend, stop: Event) -> Node:
        if friend.conversation is None:
            return super()._chat(friend, stop)
        bound = self._bound_chats.get(friend.key)
        if bound is None:
            raise IntegrationError("선택한 채팅 행에서 대화창 열기를 먼저 확인해야 합니다.")
        if not friend.selectable or friend.name != bound.name:
            raise IntegrationError("선택한 채팅 대상 정보가 변경됐습니다.")
        return super()._chat(bound, stop)

    def open_target(self, friend: Friend, scope: str, stop: Event) -> None:
        self.prepared = None
        self._check_scope(scope, stop)
        binding = friend.conversation
        if binding is None or binding.main.pid != self.driver.pid or not friend.selectable:
            raise IntegrationError("채팅 목록에서 선택한 대상이 아닙니다. 목록을 다시 확인해 주세요.")
        self.catalog = binding.main
        main, table, rows, complete = self._catalog_rows(stop)
        candidates = [(row, name) for row, name in rows if name == friend.name]
        if not complete or len(candidates) != 1:
            raise IntegrationError("선택한 채팅방이 사라졌거나 제목이 중복됐습니다. 새로고침해 주세요.")
        row, name = candidates[0]
        if (main.key != binding.main.key or table.key != binding.table_key or row.key != binding.row_key
                or not self.driver.same_element(main.native, binding.main.native)
                or not self.driver.same_element(table.native, binding.table_native)
                or not self.driver.same_element(row.native, binding.row_native)
                or self._row_key(row, name) != friend.key):
            raise IntegrationError("목록에서 선택한 채팅 행이 변경됐습니다. 새로고침해 주세요.")
        self._bound_chats.pop(friend.key, None)
        self.driver.open_conversation(main, table, row, stop)
        deadline = time.monotonic() + 3
        while True:
            checkpoint(stop)
            window = self.driver.focused_window()
            if (window is not None and matches(window, self.selectors["chat_window"])
                    and canonical(window.name) == friend.name):
                self._bound_chats[friend.key] = Friend(self._key(window), friend.name,
                    window=WindowBinding(self.driver.pid, window.key, window.native))
                break
            if time.monotonic() >= deadline:
                raise IntegrationError("선택한 채팅방의 대화창이 열렸는지 확인하지 못했습니다. 입력/전송하지 않았습니다.")
            stop.wait(.05)
    def prepare(self, friend: Friend, scope: str, stop: Event) -> None:
        self.prepared = None
        self._check_scope(scope, stop)
        if friend.key not in self._bound_chats:
            self.open_target(friend, scope, stop)
        # The same original window is checked throughout text and photo sending.
        # A successful text can reorder the chat list; later photos stay bound to
        # the verified window instead of reopening a stale list row.
        super().prepare(friend, scope, stop)
