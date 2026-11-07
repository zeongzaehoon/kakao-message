import json
import sys
import unicodedata
from types import SimpleNamespace

from kakaosender.adapters.macos import kakao_apps
from kakaosender.models import IntegrationError
from kakaosender.adapters.macos import MacDriver
from kakaosender.adapters.accessibility import Node
from threading import Event
import pytest


def application(name, identifier):
    return SimpleNamespace(localizedName=lambda: name, bundleIdentifier=lambda: identifier)


def test_kakao_detection_uses_bundle_id_and_normalizes_korean():
    by_id = application("Different localized name", "com.kakao.KakaoTalkMac")
    decomposed = application(unicodedata.normalize("NFD", "카카오톡"), "legacy")
    unrelated = application("Other app", "com.example.other")
    workspace = SimpleNamespace(runningApplications=lambda: [by_id, decomposed, unrelated])
    assert kakao_apps(workspace) == [by_id, decomposed]


def test_diagnose_reports_permission_failure_without_crashing(tmp_path, monkeypatch):
    from kakaosender.__main__ import main

    def unavailable():
        raise IntegrationError("permission missing")

    report = tmp_path / "diagnostic.json"
    monkeypatch.setattr("kakaosender.adapters.native_driver", unavailable)
    monkeypatch.setattr(sys, "argv", ["kakaosender", "--diagnose", str(report)])
    assert main() == 1
    assert json.loads(report.read_text()) == {"error": "permission missing"}


def probe_driver(monkeypatch, attributes):
    monkeypatch.setitem(sys.modules, "CoreFoundation", SimpleNamespace(CFEqual=lambda a, b: a == b))
    driver = object.__new__(MacDriver)
    driver.root = "application"
    driver.pid = 123
    driver.app = SimpleNamespace(isHidden=lambda: False, isActive=lambda: True)
    driver.ax = SimpleNamespace(
        AXUIElementCopyAttributeValue=lambda root, attr, unused: attributes.get(attr, (-25212, None)),
        AXUIElementCopyAttributeNames=lambda root, unused: (0, list(attributes)),
    )
    driver._get = lambda ref, attr, default=None: ("AXMenuBar" if ref == "menu" else "AXWindow") if attr == "AXRole" else default
    driver._node = lambda ref: Node("AXWindow", "KakaoTalk", "", ref, str(ref))
    return driver


def test_empty_windows_uses_main_and_focused_window_without_duplicates(monkeypatch):
    driver = probe_driver(monkeypatch, {
        "AXWindows": (0, []), "AXMainWindow": (0, "main"),
        "AXFocusedWindow": (0, "main"), "AXChildren": (0, ["menu", "main", "chat"]),
    })
    assert [node.native for node in driver.roots()] == ["main", "chat"]


def test_missing_windows_report_api_codes_and_fail_live_lookup(monkeypatch):
    driver = probe_driver(monkeypatch, {"AXWindows": (0, []), "AXChildren": (0, ["menu"])})
    with pytest.raises(IntegrationError, match="창"):
        driver.roots()
    result = driver.snapshot(Event())
    assert result["nodes"] == []
    assert result["error"]
    assert result["window_probe"]["AXMainWindow"]["error"] == -25212


def test_focused_chat_does_not_lose_observed_main_window(monkeypatch):
    attrs = {"AXWindows": (0, ["main"])}
    driver = probe_driver(monkeypatch, attrs)
    assert [node.key for node in driver.roots()] == ["main"]
    attrs["AXWindows"] = (0, ["chat"])
    assert {node.key for node in driver.roots()} == {"main", "chat"}
    driver._get = lambda ref, attr, default=None: "AXWindow" if ref == "chat" and attr == "AXRole" else default
    assert [node.key for node in driver.roots()] == ["chat"]


def test_current_roots_excludes_previously_cached_windows(monkeypatch):
    attrs = {"AXWindows": (0, ["main", "chat"])}
    driver = probe_driver(monkeypatch, attrs)
    assert len(driver.roots()) == 2
    attrs["AXWindows"] = (0, ["main"])
    assert [node.key for node in driver.current_roots()] == ["main"]


def test_popover_is_discovered_in_navigation_children_but_not_cached(monkeypatch):
    attrs = {"AXWindows": (0, ["main"]), "AXChildrenInNavigationOrder": (0, ["menu", "popup"])}
    driver = probe_driver(monkeypatch, attrs)
    roles = {"main": "AXWindow", "menu": "AXMenuBar", "popup": "AXPopover"}
    driver._get = lambda ref, attr, default=None: roles.get(ref, default) if attr == "AXRole" else default
    driver._node = lambda ref: Node(roles[ref], "", "", ref, ref)
    roots, diagnostics = driver._window_probe()
    assert {node.key for node in roots} == {"main", "popup"}
    assert diagnostics["AXChildrenInNavigationOrder"]["roles"] == ["AXMenuBar", "AXPopover"]
    attrs["AXChildrenInNavigationOrder"] = (0, ["menu"])
    assert [node.key for node in driver.roots()] == ["main"]


def test_focused_element_ancestry_discovers_unlisted_popover(monkeypatch):
    driver = probe_driver(monkeypatch, {"AXWindows": (0, ["main"])})
    roles = {"main": "AXWindow", "popup": "AXPopover", "button": "AXButton"}
    attributes = {("application", "AXFocusedUIElement"): "button", ("button", "AXParent"): "popup",
                  ("popup", "AXParent"): "application"}
    driver._get = lambda ref, attr, default=None: roles.get(ref, default) if attr == "AXRole" else attributes.get((ref, attr), default)
    driver._node = lambda ref: Node(roles[ref], "", "", ref, ref)
    assert {node.key for node in driver.roots()} == {"main", "popup"}


@pytest.mark.parametrize("state", ["valid", "wrong-window", "wrong-editor", "wrong-row", "other-process"])
def test_chat_list_return_key_is_only_sent_with_verified_row_and_list_focus(monkeypatch, state):
    import itertools
    monkeypatch.setitem(sys.modules, "CoreFoundation", SimpleNamespace(CFEqual=lambda a, b: a == b))
    active = SimpleNamespace(processIdentifier=lambda: 999 if state == "other-process" else 123)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(frontmostApplication=lambda: active))))
    main = Node("AXWindow", "", "Main Window", "main", "main")
    table = Node("AXTable", "", "_NS:63", "table", "table")
    row = Node("AXRow", "", "", "row", "row")
    driver = object.__new__(MacDriver)
    driver.pid, driver.root = 123, "app"
    attrs = {("app", "AXFocusedWindow"): "other" if state == "wrong-window" else "main",
             ("app", "AXFocusedUIElement"): "editor" if state == "wrong-editor" else "table",
             ("table", "AXSelectedRows"): ["other"] if state == "wrong-row" else ["row"]}
    driver._get = lambda ref, attr, default=None: attrs.get((ref, attr), default)
    driver.ax = SimpleNamespace(
        AXUIElementIsAttributeSettable=lambda ref, attr, unused: (0, True),
        AXUIElementSetAttributeValue=lambda ref, attr, value: 0)
    driver.children = lambda node: [row]
    driver._focus_window = lambda node: None
    driver.can_press = lambda node: False
    posted = []
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        CGEventCreateKeyboardEvent=lambda source, code, down: (code, down),
        CGEventSetFlags=lambda event, flags: None, kCGHIDEventTap="hid",
        CGEventPost=lambda tap, event: posted.append(event)))
    clock = itertools.count()
    monkeypatch.setattr("kakaosender.adapters.macos.time.monotonic", lambda: next(clock))
    if state == "valid":
        driver.open_conversation(main, table, row, Event())
        assert posted == [(36, True), (36, False)]
    else:
        with pytest.raises(IntegrationError, match="선택과 포커스"):
            driver.open_conversation(main, table, row, Event())
        assert posted == []


@pytest.mark.parametrize('changed', ['', 'focus', 'draft', 'photo', 'clipboard'])
def test_native_paste_dispatches_only_to_empty_verified_editor(monkeypatch, changed):
    events = []
    quartz = SimpleNamespace(
        CGEventCreateKeyboardEvent=lambda _, key, down: (key, down),
        CGEventSetFlags=lambda *args: None,
        CGEventPost=lambda tap, event: events.append(event),
        kCGEventFlagMaskCommand=1, kCGHIDEventTap=0,
    )
    monkeypatch.setitem(sys.modules, 'Quartz', quartz)
    driver = object.__new__(MacDriver)
    driver._focus_editor = lambda *args: None
    driver._editor_focus_matches = lambda *args: changed != 'focus'
    driver.read_value = lambda *args: 'draft' if changed == 'draft' else ''
    driver.photo_sheets = lambda *args: [object()] if changed == 'photo' else []
    def verify():
        if changed == 'clipboard': raise IntegrationError('clipboard changed')
    chat = Node('AXWindow', 'self', '_NS:443', object(), 'chat')
    editor = Node('AXTextArea', '', '_NS:51', object(), 'editor')
    if changed:
        with pytest.raises(IntegrationError):
            driver._paste(chat, editor, verify, Event())
        assert events == []
    else:
        driver._paste(chat, editor, verify, Event())
        assert events == [(9, True), (9, False)]


@pytest.mark.parametrize('wrong_owner', [False, True])
@pytest.mark.parametrize('action_error', [False, True])
def test_native_close_uses_only_target_window_close_button(wrong_owner, action_error):
    driver = object.__new__(MacDriver)
    chat = Node('AXWindow', 'self', '_NS:443', 'chat', 'chat')
    closed = []
    driver.refresh_node = lambda node: node
    driver.same_element = lambda a, b: a == b
    attrs = {('chat', 'AXCloseButton'): 'close', ('close', 'AXSubrole'): 'AXCloseButton',
             ('close', 'AXWindow'): 'other' if wrong_owner else 'chat'}
    driver._get = lambda ref, attr, default=None: attrs.get((ref, attr), default)
    driver._node = lambda ref: Node('AXButton', '', '', ref, ref)
    def press(node):
        from kakaosender.models import ActionOutcomeUnknown
        closed.append(node.native)
        if action_error: raise ActionOutcomeUnknown('closed but AX errored')
    driver.press = press
    driver.current_roots = lambda: []
    if wrong_owner:
        with pytest.raises(IntegrationError, match='닫기 버튼'):
            driver.close_chat(chat, Event())
        assert closed == []
    else:
        driver.close_chat(chat, Event())
        assert closed == ['close']
