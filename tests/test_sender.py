from threading import Event

import pytest

from kakaosender.adapters.accessibility import Driver, Node, matches
from kakaosender.adapters.open_chats import OpenChatsBackend
from kakaosender.models import IntegrationError


class FastEvent(Event):
    def wait(self, timeout=None):
        return self.is_set()


class FakeDriver(Driver):
    platform = "darwin"
    pid = 100

    def __init__(self):
        self.chat = "테스트 대화"
        self.value = ""
        self.writes = []
        self.presses = []
        self.handle = object()

    def roots(self):
        return [Node("AXWindow", self.chat, "_NS:443", self.handle, "chat")]

    def children(self, node):
        if node.key == "chat":
            return [Node("AXTextArea", "", "_NS:51", None, "editor"),
                    Node("AXButton", "전송", "", None, "send")]
        return []

    def read_value(self, node): return self.value
    def set_value(self, node, value):
        self.writes.append(value)
        self.value = value
    def can_write(self, node): return True
    def can_press(self, node): return True
    def enabled(self, node): return True
    def photo_sheets(self, node): return []
    def press(self, node):
        self.presses.append(node.key)
        self.value = ""


def configured(driver):
    return OpenChatsBackend(driver, {})


def test_preflight_does_not_type_then_send_preserves_unicode():
    driver = FakeDriver()
    backend = configured(driver)
    result = backend.list_friends(FastEvent())
    friend = result.friends[0]
    backend.prepare(friend, result.scope, FastEvent())
    assert not driver.writes and not driver.presses
    backend.send(friend, "안녕\n둘째 줄 👋", result.scope, FastEvent())
    assert driver.writes == ["안녕\n둘째 줄 👋"]
    assert driver.presses == ["send"]


def test_existing_draft_is_preserved():
    driver = FakeDriver()
    driver.value = "이미 작성 중"
    backend = configured(driver)
    result = backend.list_friends(FastEvent())
    with pytest.raises(IntegrationError, match="작성 중"):
        backend.prepare(result.friends[0], result.scope, FastEvent())
    assert driver.value == "이미 작성 중"
    assert not driver.writes


def test_chat_switched_between_prepare_and_send_blocks_write():
    driver = FakeDriver()
    backend = configured(driver)
    result = backend.list_friends(FastEvent())
    friend = result.friends[0]
    backend.prepare(friend, result.scope, FastEvent())
    driver.chat = "다른 사람"
    with pytest.raises(IntegrationError):
        backend.send(friend, "메시지", result.scope, FastEvent())
    assert not driver.writes and not driver.presses




def test_process_restart_blocks():
    driver = FakeDriver()
    backend = configured(driver)
    backend.expected_pid = 999
    with pytest.raises(IntegrationError, match="다시 실행"):
        backend.list_friends(FastEvent())


def test_empty_and_ambiguous_selectors_are_rejected():
    with pytest.raises(IntegrationError):
        matches(Node("Window", "name", "", None), {})
    driver = FakeDriver()
    original = driver.roots
    driver.roots = lambda: original() + original()
    with pytest.raises(IntegrationError):
        driver.one({"role": "AXWindow"}, FastEvent(), roots_only=True)




def test_send_waits_for_edit_notification_before_pressing():
    driver = FakeDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    driver.set_value = lambda *args: pytest.fail('must use normal editor input')
    calls = []
    def enter(chat, editor, text, stop):
        calls.append('paste')
        driver.value = text
    driver.enter_text = enter
    checks = iter([False, False, True])
    driver.enabled = lambda button: next(checks)
    backend.send(friend, '붙여넣기\n테스트 👋', listing.scope, FastEvent())
    assert calls == ['paste'] and driver.presses == ['send']


def test_disabled_button_never_sends_or_falls_back_to_return(monkeypatch):
    import itertools
    driver = FakeDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    driver.enabled = lambda button: False
    ticks = itertools.count()
    monkeypatch.setattr('kakaosender.adapters.sender.time.monotonic', lambda: next(ticks))
    with pytest.raises(IntegrationError, match='활성화'):
        backend.send(friend, '남아 있는 글', listing.scope, FastEvent())
    assert driver.value == '남아 있는 글' and driver.presses == []


@pytest.mark.parametrize('applied', [True, False])
def test_action_error_checks_result_without_pressing_twice(monkeypatch, applied):
    import itertools
    from kakaosender.models import ActionOutcomeUnknown, UncertainSend
    driver = FakeDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    def press(node):
        driver.presses.append(node.key)
        if applied: driver.value = ''
        raise ActionOutcomeUnknown('AX returned an error')
    driver.press = press
    ticks = itertools.count()
    monkeypatch.setattr('kakaosender.adapters.sender.time.monotonic', lambda: next(ticks))
    if applied:
        backend.send(friend, 'test', listing.scope, FastEvent())
    else:
        with pytest.raises(UncertainSend):
            backend.send(friend, 'test', listing.scope, FastEvent())
        assert driver.value == 'test'
    assert driver.presses == ['send']
