from __future__ import annotations

import sys
from .accessibility import Driver, Node
from ..models import IntegrationError


class WindowsDriver(Driver):
    platform = "win32"

    def __init__(self):
        sys.coinit_flags = 0
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        self.com = pythoncom
        try:
            import psutil
            from pywinauto import Desktop
            pids = [p.info["pid"] for p in psutil.process_iter(["name", "pid"])
                    if (p.info["name"] or "").casefold() == "kakaotalk.exe"]
            if len(pids) != 1:
                raise IntegrationError("카카오톡 프로세스를 하나만 실행하고 로그인해 주세요.")
            self.pid = pids[0]
            self.desktop = Desktop(backend="uia")
        except Exception:
            self.com.CoUninitialize()
            raise

    def _node(self, wrapper) -> Node:
        info = wrapper.element_info
        return Node(info.control_type, info.name or "", info.automation_id or "", wrapper,
                    repr(info.runtime_id))

    def roots(self) -> list[Node]:
        return [self._node(w) for w in self.desktop.windows(process=self.pid, visible_only=True)]

    def children(self, node: Node) -> list[Node]:
        return [self._node(w) for w in node.native.children()]

    def read_value(self, node: Node) -> str:
        try:
            return str(node.native.iface_value.CurrentValue or "")
        except Exception as exc:
            raise IntegrationError("이 입력창은 UIA ValuePattern 읽기를 지원하지 않습니다.") from exc

    def set_value(self, node: Node, value: str) -> None:
        if not self.can_write(node):
            raise IntegrationError("이 입력창은 UIA ValuePattern 쓰기를 지원하지 않습니다.")
        node.native.iface_value.SetValue(value)

    def can_write(self, node: Node) -> bool:
        try:
            return not node.native.iface_value.CurrentIsReadOnly
        except Exception:
            return False

    def can_press(self, node: Node) -> bool:
        try:
            return node.native.iface_invoke is not None
        except Exception:
            return False

    def enabled(self, node: Node) -> bool:
        return bool(node.native.is_enabled() and node.native.is_visible())

    def press(self, node: Node) -> None:
        if not self.can_press(node) or not self.enabled(node):
            raise IntegrationError("전송 버튼이 활성화되어 있지 않거나 Invoke를 지원하지 않습니다.")
        node.native.iface_invoke.Invoke()


    def close(self) -> None:
        self.com.CoUninitialize()
