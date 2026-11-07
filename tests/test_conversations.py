from dataclasses import replace
from threading import Event
import itertools

import pytest

from kakaosender.adapters.accessibility import Driver, Node
from kakaosender.adapters.conversations import ConversationBackend
from kakaosender.engine import execute
from kakaosender.models import IntegrationError, Plan
from kakaosender.storage import Journal


class CatalogDriver(Driver):
    platform = "darwin"
    pid = 123

    def __init__(self):
        self.main = Node("AXWindow", "메인", "Main Window", object(), "main")
        self.area = Node("AXScrollArea", "", "_NS:101", object(), "area")
        self.table = Node("AXTable", "", "_NS:63", object(), "table")
        self.rows = [Node("AXRow", "", "", object(), "one"), Node("AXRow", "", "", object(), "two")]
        self.titles = {"one": "본인 채팅", "two": "선택한 방"}
        self.windows = {}
        self.focused = None
        self.values = {}
        self.opened = []
        self.sent = []
        self.supported = True
        self.count = 2
        self.hide_main = False
        self.friends_tab = False

    def roots(self):
        return ([] if self.hide_main else [self.main]) + list(self.windows.values())

    def children(self, node):
        if node.key == "main": return [] if self.friends_tab else [self.area]
        if node.key == "area": return [self.table]
        if node.key == "table": return self.rows
        if node.role == "AXRow":
            return [Node("AXStaticText", self.titles[node.key], "_NS:40", object(), node.key + ":title")]
        if node.identifier == "_NS:443":
            return [Node("AXTextArea", "", "_NS:51", object(), node.key + ":editor"),
                    Node("AXButton", "전송", "", object(), node.key + ":send")]
        return []

    def refresh_node(self, node): return self.main if node.key == "main" else node
    def row_count(self, table): return self.count
    def can_open_conversation(self, table, row): return self.supported
    def enabled(self, node): return True

    def close_chat(self, chat, stop):
        self.windows = {key: value for key, value in self.windows.items() if value is not chat}
        self.hide_main = False

    def can_write(self, node): return True
    def can_press(self, node): return True
    def photo_sheets(self, node): return []
    def focused_window(self): return self.focused
    def read_value(self, node): return self.values.get(node.key, "")
    def set_value(self, node, value): self.values[node.key] = value

    def open_conversation(self, main, table, row, stop):
        assert main is self.main and table is self.table and row in self.rows
        self.opened.append(row.key)
        if row.key not in self.windows:
            self.windows[row.key] = Node("AXWindow", self.titles[row.key], "_NS:443", object(), row.key + ":window")
        self.focused = self.windows[row.key]
        # KakaoTalk may omit its main window after a chat receives focus.
        self.hide_main = True

    def press(self, node):
        assert node.key.endswith(":send")
        editor_key = node.key.removesuffix(":send") + ":editor"
        self.sent.append((node.key, self.values[editor_key]))
        self.values[editor_key] = ""


def test_catalog_is_listed_before_any_conversation_window_is_opened():
    driver = CatalogDriver()
    listing = ConversationBackend(driver, {}).list_friends(Event())
    assert listing.complete and len(listing.friends) == 2
    assert all(friend.selectable and friend.conversation and not friend.window for friend in listing.friends)
    assert not driver.opened and not driver.windows and not driver.sent


def test_multiple_selected_rows_are_opened_and_sent_in_order_without_manual_windows(tmp_path):
    driver = CatalogDriver()
    listing = ConversationBackend(driver, {}).list_friends(Event())
    backend = ConversationBackend(driver, {}, listing.session_pid, listing.catalog)
    journal = Journal(tmp_path / "attempts.sqlite3")
    try:
        results = execute(Plan(listing.friends, "테스트", listing.scope, True, 0), backend, journal, Event(), lambda result: None)
    finally:
        journal.close()
    assert [result.state for result in results] == ["submitted", "submitted"]
    assert driver.opened == ["one", "two"]
    assert driver.sent == [("one:window:send", "테스트"), ("two:window:send", "테스트")]


@pytest.mark.parametrize("change", ["removed", "renamed", "replaced", "duplicate", "restarted", "count"])
def test_changed_catalog_target_blocks_opening_and_sending(change):
    driver = CatalogDriver()
    backend = ConversationBackend(driver, {})
    listing = backend.list_friends(Event())
    if change == "removed": driver.rows.pop(0)
    if change == "renamed": driver.titles["one"] = "바뀐 제목"
    if change == "replaced": driver.rows[0] = replace(driver.rows[0], native=object())
    if change == "duplicate": driver.titles["two"] = driver.titles["one"]
    if change == "restarted": driver.pid = 456
    if change == "count": driver.count = 999
    with pytest.raises(IntegrationError):
        backend.prepare(listing.friends[0], listing.scope, Event())
    assert not driver.opened and not driver.sent


def test_friends_tab_cannot_be_misread_as_chat_list():
    driver = CatalogDriver()
    driver.friends_tab = True
    with pytest.raises(IntegrationError, match="채팅 탭"):
        ConversationBackend(driver, {}).list_friends(Event())


def test_unsupported_row_open_is_disabled():
    driver = CatalogDriver()
    driver.supported = False
    listing = ConversationBackend(driver, {}).list_friends(Event())
    assert all(not friend.selectable for friend in listing.friends)
    assert not driver.opened


def test_wrong_focused_chat_after_open_stops_before_input(monkeypatch):
    driver = CatalogDriver()
    backend = ConversationBackend(driver, {})
    listing = backend.list_friends(Event())
    driver.open_conversation = lambda *args: setattr(driver, "focused", Node("AXWindow", "다른 방", "_NS:443", object(), "other"))
    clock = itertools.count()
    monkeypatch.setattr("kakaosender.adapters.conversations.time.monotonic", lambda: next(clock))
    with pytest.raises(IntegrationError, match="열렸는지"):
        backend.prepare(listing.friends[0], listing.scope, Event())
    assert not driver.values and not driver.sent


def test_existing_draft_is_preserved_after_automatic_open():
    driver = CatalogDriver()
    backend = ConversationBackend(driver, {})
    listing = backend.list_friends(Event())
    driver.values["one:window:editor"] = "기존 초안"
    with pytest.raises(IntegrationError, match="작성 중"):
        backend.prepare(listing.friends[0], listing.scope, Event())
    assert driver.values["one:window:editor"] == "기존 초안" and not driver.sent


def test_photo_after_text_stays_with_verified_window_when_list_rows_are_recreated(tmp_path):
    from test_photos import photo_file
    from kakaosender.attachments import load_photo
    driver = CatalogDriver()
    driver.supports_photos = True
    backend = ConversationBackend(driver, {})
    listing = backend.list_friends(Event())
    friend = listing.friends[0]
    original_send = backend.send
    photos_sent = []
    def send_and_reorder(*args):
        original_send(*args)
        driver.rows = [replace(row, native=object()) for row in reversed(driver.rows)]
    backend.send = send_and_reorder
    backend.send_photo = lambda friend, photo, scope, stop: photos_sent.append(backend._chat(friend, stop).key)
    journal = Journal(tmp_path / "photo-attempts.sqlite3")
    try:
        result = execute(Plan((friend,), "테스트", listing.scope, True, 0, (load_photo(photo_file(tmp_path)),)),
                         backend, journal, Event(), lambda result: None)
    finally:
        journal.close()
    assert result[0].state == "submitted"
    assert driver.opened == ["one"]
    assert photos_sent == ["one:window"]
