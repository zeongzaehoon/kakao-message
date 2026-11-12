from __future__ import annotations

from threading import Event
from contextlib import contextmanager
from collections.abc import Callable, Iterator
import time
from ..attachments import Photo

from .accessibility import Driver, Node
from ..models import ActionOutcomeUnknown, IntegrationError, canonical, checkpoint


def kakao_apps(workspace) -> list:
    return [app for app in workspace.runningApplications()
            if str(app.bundleIdentifier()) == "com.kakao.KakaoTalkMac"
            or canonical(str(app.localizedName())) in {"KakaoTalk", "카카오톡"}]


def connection_status() -> dict:
    """Read permission and process metadata, without reading another app's UI."""
    import ApplicationServices as AX
    from AppKit import NSWorkspace
    from Foundation import NSBundle
    bundle = NSBundle.mainBundle()
    apps = kakao_apps(NSWorkspace.sharedWorkspace())
    return {
        "accessibility_trusted": bool(AX.AXIsProcessTrusted()),
        "app_path": str(bundle.bundlePath()),
        "bundle_id": str(bundle.bundleIdentifier() or ""),
        "kakao_process_count": len(apps),
    }


class InvalidAccessibilityElement(IntegrationError):
    """A read encountered an AX element removed during a UI update."""


class MacDriver(Driver):
    platform = "darwin"
    supports_photos = True

    def __init__(self):
        import ApplicationServices as AX
        from AppKit import NSWorkspace
        self.ax = AX
        if not AX.AXIsProcessTrusted():
            raise IntegrationError("이 앱의 손쉬운 사용 권한이 없습니다. ‘연결 설정’에서 ‘연결 상태 확인’을 눌러 실행 중인 앱을 확인한 뒤 해당 앱을 허용해 주세요. 다른 복사본을 허용한 경우에는 적용되지 않습니다.")
        apps = kakao_apps(NSWorkspace.sharedWorkspace())
        if len(apps) != 1:
            raise IntegrationError("카카오톡 앱을 하나만 실행하고 로그인해 주세요.")
        self.app = apps[0]
        self.pid = self.app.processIdentifier()
        # A timeout on only the application element does not cover child elements.
        AX.AXUIElementSetMessagingTimeout(AX.AXUIElementCreateSystemWide(), 2.0)
        self.root = AX.AXUIElementCreateApplication(self.pid)
        AX.AXUIElementSetMessagingTimeout(self.root, 2.0)

    def _get(self, ref, attribute, default=None):
        code, value = self.ax.AXUIElementCopyAttributeValue(ref, attribute, None)
        return value if code == 0 else default

    def _node(self, ref) -> Node:
        name = self._get(ref, "AXTitle") or self._get(ref, "AXDescription") or ""
        # Static text often stores its label in AXValue; editors are excluded.
        role = str(self._get(ref, "AXRole", ""))
        if not name and role == "AXStaticText":
            name = self._get(ref, "AXValue", "")
        from CoreFoundation import CFHash
        return Node(role, str(name), str(self._get(ref, "AXIdentifier", "")), ref, str(CFHash(ref)))

    def refresh_node(self, node: Node) -> Node:
        return self._node(node.native)

    def roots(self) -> list[Node]:
        windows, _ = self._window_probe()
        if not windows:
            raise IntegrationError("카카오톡의 창을 접근성 API에서 찾지 못했습니다. 채팅 탭이 보이는데도 이 오류가 나오면 ‘진단 JSON 저장’으로 진단 결과를 확인해 주세요.")
        return windows

    def current_roots(self) -> list[Node]:
        roots, _ = self._window_probe(retain=False)
        return roots

    def same_element(self, first: object, second: object) -> bool:
        from CoreFoundation import CFEqual
        return bool(CFEqual(first, second))

    def row_count(self, table: Node) -> int | None:
        count = self._get(table.native, "AXRowCount")
        return int(count) if isinstance(count, (int, float)) and count >= 0 else None

    def _settable(self, node: Node, attribute: str) -> bool:
        code, writable = self.ax.AXUIElementIsAttributeSettable(node.native, attribute, None)
        return code == 0 and bool(writable)

    def can_open_conversation(self, table: Node, row: Node) -> bool:
        return self.can_press(row) or (self._settable(table, "AXSelectedRows") and self._settable(table, "AXFocused"))

    def focused_window(self) -> Node | None:
        ref = self._get(self.root, "AXFocusedWindow")
        return self._node(ref) if ref is not None else None

    def open_conversation(self, main: Node, table: Node, row: Node, stop: Event) -> None:
        """Select an exact chat-list row, verify focus, and activate with Return."""
        import Quartz
        checkpoint(stop)
        self._focus_window(main)
        if not any(self.same_element(child.native, row.native) for child in self.children(table)):
            raise IntegrationError("선택한 행이 현재 채팅 목록에 없습니다.")
        if self.can_press(row):
            self.press(row)
            return
        if not self.can_open_conversation(table, row):
            raise IntegrationError("채팅 목록이 접근성 행 선택 또는 포커스 변경을 지원하지 않습니다.")
        if self.ax.AXUIElementSetAttributeValue(table.native, "AXSelectedRows", [row.native]) != 0:
            raise IntegrationError("채팅 목록의 대상 행을 선택하지 못했습니다.")
        if self.ax.AXUIElementSetAttributeValue(table.native, "AXFocused", True) != 0:
            raise IntegrationError("채팅 목록에 초점을 맞추지 못했습니다.")
        deadline = time.monotonic() + 1
        while not self._conversation_focus_matches(main, table, row):
            checkpoint(stop)
            if time.monotonic() >= deadline:
                raise IntegrationError("대상 채팅 행의 선택과 포커스를 확인하지 못했습니다. 열기 키를 누르지 않았습니다.")
            stop.wait(.05)
        down = Quartz.CGEventCreateKeyboardEvent(None, 36, True)
        up = Quartz.CGEventCreateKeyboardEvent(None, 36, False)
        if down is None or up is None:
            raise IntegrationError("대화방 열기 키 이벤트를 만들지 못했습니다.")
        checkpoint(stop)
        if not self._conversation_focus_matches(main, table, row):
            raise IntegrationError("대화방 열기 직전에 포커스가 변경됐습니다.")
        for event in (down, up):
            Quartz.CGEventSetFlags(event, 0)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def _conversation_focus_matches(self, main: Node, table: Node, row: Node) -> bool:
        from AppKit import NSWorkspace
        active = NSWorkspace.sharedWorkspace().frontmostApplication()
        window = self._get(self.root, "AXFocusedWindow")
        focused = self._get(self.root, "AXFocusedUIElement")
        selected = self._get(table.native, "AXSelectedRows", []) or []
        return bool(active and active.processIdentifier() == self.pid
                    and window is not None and self.same_element(window, main.native)
                    and focused is not None and any(self.same_element(focused, ref) for ref in (table.native, row.native))
                    and len(selected) == 1 and self.same_element(selected[0], row.native))

    def _window_probe(self, retain: bool = True) -> tuple[list[Node], dict]:
        from CoreFoundation import CFEqual
        windows = []
        diagnostics = {}
        containers = {"AXWindow", "AXPopover", "AXSheet", "AXDialog", "AXGroup", "AXUnknown", "AXLayoutArea"}
        arrays = {"AXWindows", "AXChildren", "AXChildrenInNavigationOrder"}
        for attribute in ("AXWindows", "AXMainWindow", "AXFocusedWindow", "AXChildren", "AXChildrenInNavigationOrder"):
            code, value = self.ax.AXUIElementCopyAttributeValue(self.root, attribute, None)
            refs = []
            if code == 0 and value is not None:
                refs = list(value) if attribute in arrays else [value]
            roles = [str(self._get(ref, "AXRole", "")) for ref in refs]
            diagnostics[attribute] = {"error": code, "count": len(refs), "roles": roles}
            for ref, role in zip(refs, roles):
                if role not in containers:
                    continue
                if not any(CFEqual(ref, window.native) for window in windows):
                    windows.append(self._node(ref))
        # A transient profile can be reachable through focus ancestry even when
        # KakaoTalk omits it from AXWindows. Never retain these transient handles.
        focused = self._get(self.root, "AXFocusedUIElement")
        seen = []
        while focused is not None and len(seen) < 35:
            if CFEqual(focused, self.root) or any(CFEqual(focused, ref) for ref in seen):
                break
            seen.append(focused)
            parent = self._get(focused, "AXParent")
            role = self._get(focused, "AXRole")
            if (role in {"AXWindow", "AXPopover", "AXSheet", "AXDialog"}
                    or (role in containers and parent is not None and CFEqual(parent, self.root))):
                if not any(CFEqual(focused, node.native) for node in windows):
                    windows.append(self._node(focused))
            focused = parent
        diagnostics["focus_ancestor_roles"] = [str(self._get(ref, "AXRole", "")) for ref in seen]
        # KakaoTalk sometimes exposes only the focused window. Retain previously
        # observed handles only while AX still reports them as live windows.
        cached = 0
        for previous in getattr(self, "_known_windows", []) if retain else []:
            if (self._get(previous.native, "AXRole") == "AXWindow"
                    and not any(CFEqual(previous.native, window.native) for window in windows)):
                windows.append(self._node(previous.native))
                cached += 1
        self._known_windows = [node for node in windows if node.role == "AXWindow"]
        diagnostics["retained_live_windows"] = cached
        code, attributes = self.ax.AXUIElementCopyAttributeNames(self.root, None)
        diagnostics["supported_attributes"] = list(attributes or []) if code == 0 else []
        diagnostics["app_hidden"] = bool(self.app.isHidden())
        diagnostics["app_active"] = bool(self.app.isActive())
        return windows, diagnostics

    def snapshot(self, stop: Event) -> dict:
        windows, diagnostics = self._window_probe()
        nodes = []
        for node, depth, path in self.walk(windows, stop):
            item = {**node.metadata(), "depth": depth, "path": path}
            if node.role == "AXTable":
                item["row_count"] = self.row_count(node)
                item["selected_rows_writable"] = self._settable(node, "AXSelectedRows")
                item["focus_writable"] = self._settable(node, "AXFocused")
            if node.role in {"AXWindow", "AXRow", "AXButton", "AXTextArea", "AXTextField"}:
                code, actions = self.ax.AXUIElementCopyActionNames(node.native, None)
                item["actions"] = list(actions or []) if code == 0 else []
                item["enabled"] = self.enabled(node)
                item["subrole"] = str(self._get(node.native, "AXSubrole", ""))
                if node.role in {"AXTextArea", "AXTextField"}:
                    item["value_writable"] = self.can_write(node)
            nodes.append(item)
        result = {
            "platform": self.platform, "pid": self.pid,
            "note": "진단에는 화면의 이름이 포함됩니다. 메시지 입력 값은 수집하지 않습니다.",
            "window_probe": diagnostics,
            "nodes": nodes,
        }
        if not windows:
            result["error"] = "카카오톡 창을 접근성 API에서 찾지 못했습니다. 채팅 탭이 보이는 상태라면 저장한 진단 JSON의 window_probe 정보를 확인해 주세요."
        return result

    def children(self, node: Node) -> list[Node]:
        code, children = self.ax.AXUIElementCopyAttributeValue(node.native, "AXChildren", None)
        if code in {-25205, -25212}:  # unsupported attribute / no value: leaf
            return []
        if code == -25202:
            raise InvalidAccessibilityElement("카카오톡 화면 요소가 갱신되어 다시 읽어야 합니다 (-25202).")
        if code != 0:
            raise IntegrationError(f"접근성 자식 요소 읽기 실패: {code}")
        return [self._node(ref) for ref in (children or [])]

    def _search_parent(self, parent: Node) -> Node:
        fresh = self.refresh_node(parent)
        if (not fresh.role or fresh.role != parent.role or fresh.identifier != parent.identifier
                or canonical(fresh.name) != canonical(parent.name) or fresh.key != parent.key
                or not self.same_element(fresh.native, parent.native)):
            raise IntegrationError("화면을 읽는 동안 대상이 변경되었습니다. 목록을 새로고침해 주세요.")
        return fresh

    def chat_controls(self, chat: Node, selectors: dict, stop: Event) -> tuple[Node, Node]:
        # The composer is separate from the virtualized message history.
        # Never walk history rows to locate input controls: their AX handles
        # can disappear while a newly opened conversation loads messages.
        area = self.one({"role": "AXScrollArea", "identifier": "_NS:47"},
                        stop, chat, roots_only=True)
        editor = self.one(selectors["editor"], stop, area, roots_only=True)
        button = self.one(selectors["send_button"], stop, chat, roots_only=True)
        self._search_parent(chat)
        return editor, button

    def find(self, selector: dict, stop: Event, parent: Node | None = None,
             recipient: str = "", roots_only: bool = False) -> list[Node]:
        # A newly opened chat can replace descendants while AX is walking them.
        # Discard the entire partial read; never skip a stale branch (it might
        # hide a duplicate control), rebind the parent, or repeat a UI action.
        for attempt in range(3):
            checkpoint(stop)
            current = self._search_parent(parent) if parent is not None else None
            try:
                found = super().find(selector, stop, current, recipient, roots_only)
            except InvalidAccessibilityElement as exc:
                if attempt == 2:
                    raise IntegrationError("카카오톡 화면이 계속 변경되어 입력/전송 대상을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요 (-25202).") from exc
                stop.wait(.1)
                continue
            checkpoint(stop)
            if parent is not None:
                self._search_parent(parent)
            return found
        return []

    def read_value(self, node: Node) -> str:
        value = self._get(node.native, "AXValue")
        if not isinstance(value, str):
            raise IntegrationError("이 입력창은 문자열 AXValue 읽기를 지원하지 않습니다.")
        return value

    def set_value(self, node: Node, value: str) -> None:
        if not self.can_write(node):
            raise IntegrationError("이 입력창은 AXValue 쓰기를 지원하지 않습니다.")
        code = self.ax.AXUIElementSetAttributeValue(node.native, "AXValue", value)
        if code != 0:
            raise IntegrationError(f"입력창 쓰기 실패: {code}")

    def can_write(self, node: Node) -> bool:
        code, value = self.ax.AXUIElementIsAttributeSettable(node.native, "AXValue", None)
        return code == 0 and bool(value)

    def can_press(self, node: Node) -> bool:
        code, actions = self.ax.AXUIElementCopyActionNames(node.native, None)
        return code == 0 and "AXPress" in (actions or [])

    def enabled(self, node: Node) -> bool:
        return bool(self._get(node.native, "AXEnabled", False))

    def press(self, node: Node) -> None:
        if not self.can_press(node) or not self.enabled(node):
            raise IntegrationError("버튼의 AXPress 동작을 사용할 수 없습니다.")
        code = self.ax.AXUIElementPerformAction(node.native, "AXPress")
        if code != 0:
            raise ActionOutcomeUnknown(f"AXPress 결과 확인 필요: {code}")


    def photo_sheets(self, chat: Node) -> list[Node]:
        from CoreFoundation import CFEqual
        refs = list(self._get(chat.native, "AXSheets", []) or [])
        refs.extend(child.native for child in self.children(chat) if child.role == "AXSheet")
        unique = []
        for ref in refs:
            if not any(CFEqual(ref, node.native) for node in unique):
                unique.append(self._node(ref))
        return unique

    @contextmanager
    def photo_clipboard(self, photo: Photo) -> Iterator[Callable[[], None]]:
        from AppKit import NSImage
        from Foundation import NSData
        image = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(photo.content, len(photo.content)))
        if image is None:
            raise IntegrationError("전송할 사진을 macOS 이미지로 읽지 못했습니다.")
        with self._clipboard_objects([image]) as verify:
            self._photo_clipboard_check = verify
            try:
                yield verify
            finally:
                self._photo_clipboard_check = None

    @contextmanager
    def _clipboard_objects(self, objects: list) -> Iterator[Callable[[], None]]:
        from AppKit import NSPasteboard, NSPasteboardItem
        board = NSPasteboard.generalPasteboard()
        before = board.changeCount()
        saved = []
        for item in board.pasteboardItems() or []:
            copy = NSPasteboardItem.alloc().init()
            for kind in item.types():
                value = item.dataForType_(kind)
                if value is None or not copy.setData_forType_(value, kind):
                    raise IntegrationError("기존 클립보드를 보관하지 못했습니다.")
            saved.append(copy)
        if board.changeCount() != before:
            raise IntegrationError("클립보드가 변경돼 붙여넣기를 중단했습니다.")
        owned = board.clearContents()
        try:
            if not board.writeObjects_(objects):
                raise IntegrationError("붙여넣을 내용을 클립보드에 준비하지 못했습니다.")
            owned = board.changeCount()

            def verify() -> None:
                if board.changeCount() != owned:
                    raise IntegrationError("클립보드가 변경돼 붙여넣기를 중단했습니다.")

            yield verify
        finally:
            # Preserve any new content the user copied during this operation.
            if board.changeCount() == owned:
                board.clearContents()
                if saved and not board.writeObjects_(saved):
                    raise IntegrationError("기존 클립보드를 복원하지 못했습니다. 전송 결과를 확인해 주세요.")

    def _editor_focus_matches(self, chat: Node, editor: Node) -> bool:
        from AppKit import NSWorkspace
        active = NSWorkspace.sharedWorkspace().frontmostApplication()
        focused = self._get(self.root, "AXFocusedUIElement")
        window = self._get(self.root, "AXFocusedWindow")
        return bool(active and active.processIdentifier() == self.pid
                    and focused is not None and window is not None
                    and self.same_element(focused, editor.native) and self.same_element(window, chat.native))

    def _focus_editor(self, chat: Node, editor: Node, stop: Event) -> None:
        checkpoint(stop)
        self._focus_window(chat)
        if self.ax.AXUIElementSetAttributeValue(editor.native, "AXFocused", True) != 0:
            raise IntegrationError("대화 입력창에 초점을 맞추지 못했습니다.")
        deadline = time.monotonic() + 1
        while not self._editor_focus_matches(chat, editor):
            checkpoint(stop)
            if time.monotonic() >= deadline:
                raise IntegrationError("대화창과 입력창 초점을 확인하지 못했습니다.")
            stop.wait(.05)

    def _paste(self, chat: Node, editor: Node, verify: Callable[[], None], stop: Event) -> None:
        import Quartz
        self._focus_editor(chat, editor, stop)
        down = Quartz.CGEventCreateKeyboardEvent(None, 9, True)
        up = Quartz.CGEventCreateKeyboardEvent(None, 9, False)
        if down is None or up is None:
            raise IntegrationError("붙여넣기 이벤트를 만들지 못했습니다.")
        checkpoint(stop)
        verify()
        if not self._editor_focus_matches(chat, editor) or self.read_value(editor) or self.photo_sheets(chat):
            raise IntegrationError("붙여넣기 직전에 초점 또는 입력 내용이 변경됐습니다.")
        # Normal AppKit editing dispatch; no coordinates and no Return fallback.
        for event in (down, up):
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def enter_text(self, chat: Node, editor: Node, message: str, stop: Event) -> None:
        from AppKit import NSPasteboardItem, NSPasteboardTypeString
        item = NSPasteboardItem.alloc().init()
        if not item.setString_forType_(message, NSPasteboardTypeString):
            raise IntegrationError("메시지를 붙여넣기 형식으로 준비하지 못했습니다.")
        with self._clipboard_objects([item]) as verify:
            self._paste(chat, editor, verify, stop)
            deadline = time.monotonic() + 3
            while True:
                checkpoint(stop)
                verify()
                value = self.read_value(editor).replace("\r\n", "\n")
                if value == message.replace("\r\n", "\n"):
                    return
                if value or time.monotonic() >= deadline:
                    raise IntegrationError("붙여넣은 메시지가 원문과 일치하지 않습니다. 전송하지 않았습니다.")
                stop.wait(.05)

    def paste_photo(self, chat: Node, editor: Node) -> None:
        verify = getattr(self, "_photo_clipboard_check", None)
        if verify is None:
            raise IntegrationError("전송할 사진의 클립보드 준비를 확인하지 못했습니다.")
        self._paste(chat, editor, verify, Event())

    def close_chat(self, chat: Node, stop: Event) -> None:
        checkpoint(stop)
        current = self.refresh_node(chat)
        if current.role != "AXWindow" or current.identifier != "_NS:443" or current.name != chat.name:
            raise IntegrationError("닫을 대화창이 변경됐습니다.")
        ref = self._get(chat.native, "AXCloseButton")
        owner = self._get(ref, "AXWindow") if ref is not None else None
        if ref is None or owner is None or not self.same_element(owner, chat.native):
            raise IntegrationError("해당 대화창의 닫기 버튼을 확인하지 못했습니다.")
        button = self._node(ref)
        if button.role != "AXButton" or self._get(ref, "AXSubrole") != "AXCloseButton":
            raise IntegrationError("대화창 닫기 버튼이 아닙니다.")
        checkpoint(stop)
        try:
            self.press(button)
        except ActionOutcomeUnknown:
            # A failing AX return can follow a successful close. Observe once;
            # never click again or use a keyboard fallback.
            pass
        deadline = time.monotonic() + 2
        while True:
            # A closed AX object can remain readable; visibility is checked too.
            role = self._get(chat.native, "AXRole")
            windows = self.current_roots()
            present = any(self.same_element(node.native, chat.native) for node in windows)
            if role != "AXWindow" or (not present and self._get(chat.native, "AXVisible") is False):
                return
            if time.monotonic() >= deadline:
                raise IntegrationError("전송은 완료됐지만 대화창이 닫혔는지 확인하지 못했습니다.")
            time.sleep(.05)


    def _focus_window(self, main: Node) -> None:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSWorkspace
        from CoreFoundation import CFEqual
        if not self.app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps):
            raise IntegrationError("카카오톡을 활성화하지 못했습니다.")
        if self.ax.AXUIElementPerformAction(main.native, "AXRaise") != 0:
            raise IntegrationError("선택한 카카오톡 창을 활성화하지 못했습니다.")
        deadline = time.monotonic() + 1
        while True:
            active = NSWorkspace.sharedWorkspace().frontmostApplication()
            focused = self._get(self.root, "AXFocusedWindow")
            if active and active.processIdentifier() == self.pid and focused is not None and CFEqual(focused, main.native):
                break
            if time.monotonic() >= deadline:
                raise IntegrationError("선택한 카카오톡 창의 초점을 확인하지 못했습니다.")
            time.sleep(0.05)
