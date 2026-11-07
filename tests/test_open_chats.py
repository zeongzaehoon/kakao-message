from dataclasses import replace
import json
from threading import Event

import pytest

from kakaosender.adapters.accessibility import Driver, Node
from kakaosender.adapters.open_chats import OpenChatsBackend
from kakaosender.models import IntegrationError
from kakaosender.open_chat_checks import confirmed_self_target


class OpenDriver(Driver):
    platform = "darwin"
    pid = 234

    def __init__(self):
        self.windows = [Node("AXWindow", "나와의 채팅", "_NS:443", object(), "chat-1")]
        self.value = ""
        self.writes = []
        self.presses = []
        self.writable = True
        self.pressable = True
        self.after_write = lambda: None

    def roots(self):
        return [Node("AXWindow", "메인 창", "Main Window", object(), "main")] + self.windows

    def children(self, node):
        assert node.key != "main", "The main window and friend list must never be traversed"
        if node.role == "AXWindow":
            return [Node("AXTextArea", "", "_NS:51", object(), node.key + ":editor"),
                    Node("AXButton", "전송", "", object(), node.key + ":send")]
        return []

    def enabled(self, node): return True

    def can_write(self, node): return self.writable
    def can_press(self, node): return self.pressable
    def read_value(self, node): return self.value
    def photo_sheets(self, node): return []

    def set_value(self, node, value):
        self.writes.append((node.key, value))
        self.value = value
        self.after_write()

    def press(self, node):
        self.presses.append(node.key)
        self.value = ""

    def open_self(self, *args): pytest.fail("Must not open a profile")
    def open_friend(self, *args): pytest.fail("Must not open a friend")


def configured():
    driver = OpenDriver()
    backend = OpenChatsBackend(driver, {})
    listing = backend.list_friends(Event())
    return driver, backend, listing


def test_open_chat_listing_and_send_do_not_touch_friends_or_click_coordinates():
    driver, backend, listing = configured()
    assert listing.complete
    assert [chat.name for chat in listing.friends] == ["나와의 채팅"]
    chat = listing.friends[0]
    # The UI creates a new backend for sending; the selected native handle survives.
    sender = OpenChatsBackend(driver, {}, listing.session_pid)
    sender.prepare(chat, listing.scope, Event())
    assert driver.writes == driver.presses == []
    sender.send(chat, "첫 줄\n둘째 줄 👋", listing.scope, Event())
    assert driver.writes == [("chat-1:editor", "첫 줄\n둘째 줄 👋")]
    assert driver.presses == ["chat-1:send"]


@pytest.mark.parametrize("change", ["closed", "replaced", "renamed", "duplicate", "hash-reused", "restarted"])
def test_window_change_between_selection_and_send_blocks_all_input(change):
    driver, backend, listing = configured()
    original = driver.windows[0]
    if change == "closed": driver.windows = []
    if change == "replaced": driver.windows = [replace(original, key="chat-2", native=object())]
    if change == "renamed": driver.windows = [replace(original, name="다른 대화")]
    if change == "duplicate": driver.windows.append(replace(original, key="chat-2", native=object()))
    if change == "hash-reused": driver.windows = [replace(original, native=object())]
    if change == "restarted": driver.pid = 567
    with pytest.raises(IntegrationError):
        backend.prepare(listing.friends[0], listing.scope, Event())
    assert driver.writes == driver.presses == []


def test_window_replaced_after_text_entry_cannot_press_another_chat_send_button():
    driver, backend, listing = configured()
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, Event())
    driver.after_write = lambda: setattr(driver, "windows", [replace(driver.windows[0], native=object())])
    with pytest.raises(IntegrationError, match="교체"):
        backend.send(friend, "테스트", listing.scope, Event())
    assert not driver.presses


def test_existing_draft_and_attachment_confirmation_are_preserved():
    driver, backend, listing = configured()
    driver.value = "작성 중인 글"
    with pytest.raises(IntegrationError, match="작성 중"):
        backend.prepare(listing.friends[0], listing.scope, Event())
    assert driver.value == "작성 중인 글"
    driver.value = ""
    driver.photo_sheets = lambda node: [object()]
    with pytest.raises(IntegrationError, match="첨부"):
        backend.prepare(listing.friends[0], listing.scope, Event())
    assert driver.writes == driver.presses == []


@pytest.mark.parametrize("unsupported", ["writable", "pressable", "duplicate"])
def test_ambiguous_or_unsupported_chat_is_disabled_in_listing(unsupported):
    driver = OpenDriver()
    if unsupported == "duplicate":
        driver.windows.append(replace(driver.windows[0], key="chat-2", native=object()))
    else:
        setattr(driver, unsupported, False)
    listing = OpenChatsBackend(driver, {}).list_friends(Event())
    assert listing.friends and all(not chat.selectable for chat in listing.friends)


def test_self_test_requires_explicit_confirmation_and_exact_current_target(tmp_path):
    driver, backend, listing = configured()
    friend = listing.friends[0]
    target = tmp_path / "target.json"
    payload = {"pid": driver.pid, "key": friend.key, "name": friend.name}
    target.write_text(json.dumps(payload))
    with pytest.raises(IntegrationError, match="본인"):
        confirmed_self_target(backend, target)
    payload["confirmed_self_chat"] = True
    target.write_text(json.dumps(payload))
    assert confirmed_self_target(backend, target) == (friend, listing.scope)
    driver.windows = [replace(driver.windows[0], key="replacement", native=object())]
    with pytest.raises(IntegrationError, match="변경"):
        confirmed_self_target(backend, target)
    assert driver.writes == driver.presses == []


def test_explicit_self_draft_clear_never_sends_and_requires_confirmed_target(tmp_path, monkeypatch):
    from kakaosender.open_chat_checks import run_clear_self_draft
    driver, backend, listing = configured()
    children = driver.children
    handles = {}
    driver.children = lambda node: [replace(child, native=handles.setdefault(child.key, object())) for child in children(node)]
    friend = listing.friends[0]
    target = tmp_path / "self.json"
    payload = {"pid": driver.pid, "key": friend.key, "name": friend.name, "confirmed_self_chat": True}
    target.write_text(json.dumps(payload))
    report = tmp_path / "report.json"
    monkeypatch.setattr("kakaosender.adapters.native_driver", lambda: driver)
    monkeypatch.setattr("kakaosender.open_chat_checks.self_test_backend", lambda driver, path: backend)
    driver.value = "사용자가 비우라고 한 초안"
    assert run_clear_self_draft(report, target) == 0
    assert driver.value == "" and driver.writes == [("chat-1:editor", "")]
    assert not driver.presses and json.loads(report.read_text())["sent"] == 0
    driver.value = "다른 초안"
    payload["confirmed_self_chat"] = False
    target.write_text(json.dumps(payload))
    assert run_clear_self_draft(report, target) == 1
    assert driver.value == "다른 초안" and not driver.presses


@pytest.mark.parametrize('changed', ['draft', 'photo', 'window'])
def test_close_preserves_new_draft_photo_or_replaced_window(changed):
    driver, backend, listing = configured()
    friend = listing.friends[0]
    driver.close_chat = lambda *args: pytest.fail('must not close')
    if changed == 'draft': driver.value = '새 초안'
    if changed == 'photo': driver.photo_sheets = lambda node: [object()]
    if changed == 'window': driver.windows[0] = replace(driver.windows[0], native=object())
    with pytest.raises(IntegrationError):
        backend.finish_recipient(friend, listing.scope, Event())


def test_self_close_check_never_sends(tmp_path, monkeypatch):
    from kakaosender.open_chat_checks import run_close_self_chat
    driver, backend, listing = configured()
    friend = listing.friends[0]
    target = tmp_path / 'self.json'
    target.write_text(json.dumps(dict(pid=driver.pid, key=friend.key, name=friend.name, confirmed_self_chat=True)))
    closed = []
    driver.close_chat = lambda chat, stop: closed.append(chat.key)
    monkeypatch.setattr('kakaosender.adapters.native_driver', lambda: driver)
    report = tmp_path / 'closed.json'
    assert run_close_self_chat(report, target) == 0
    assert closed == ['chat-1'] and not driver.writes and not driver.presses
    assert json.loads(report.read_text())['sent'] == 0
