from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from threading import Event
from contextlib import AbstractContextManager
from collections.abc import Callable
from ..attachments import Photo
from ..models import IntegrationError, canonical, checkpoint


@dataclass
class Node:
    role: str
    name: str
    identifier: str
    native: Any = field(repr=False)
    key: str = ""

    def metadata(self) -> dict:
        return {"role": self.role, "name": self.name, "identifier": self.identifier}


def matches(node: Node, selector: dict, recipient: str = "") -> bool:
    if not selector or not any(selector.values()):
        raise IntegrationError("화면 요소 설정이 비어 있습니다. 연결 설정을 완료해 주세요.")
    for key, expected in selector.items():
        if key not in {"role", "name", "identifier"}:
            raise IntegrationError(f"지원하지 않는 선택 조건: {key}")
        if not isinstance(expected, str):
            raise IntegrationError("선택 조건의 값은 문자열이어야 합니다.")
        expected = expected.replace("{recipient}", recipient)
        if expected and canonical(getattr(node, key)) != canonical(expected):
            return False
    return True


class Driver:
    platform: str
    pid: int
    supports_photos = False

    def roots(self) -> list[Node]:
        raise NotImplementedError

    def current_roots(self) -> list[Node]:
        return self.roots()

    def same_element(self, first: object, second: object) -> bool:
        return first is second

    def row_count(self, table: Node) -> int | None:
        return None

    def can_open_conversation(self, table: Node, row: Node) -> bool:
        return False

    def open_conversation(self, main: Node, table: Node, row: Node, stop: Event) -> None:
        raise IntegrationError("채팅 목록에서 대화방을 여는 동작을 지원하지 않습니다.")

    def focused_window(self) -> Node | None:
        return None

    def children(self, node: Node) -> list[Node]:
        raise NotImplementedError

    def walk(self, roots: list[Node], stop: Event, max_nodes=5000) -> list[tuple[Node, int, str]]:
        stack = [(n, 0, str(i)) for i, n in reversed(list(enumerate(roots)))]
        found = []
        while stack:
            checkpoint(stop)
            node, depth, path = stack.pop()
            found.append((node, depth, path))
            if len(found) > max_nodes or depth > 35:
                raise IntegrationError("화면 요소가 너무 많습니다. 불필요한 카카오톡 창을 닫고 다시 시도해 주세요.")
            for i, child in reversed(list(enumerate(self.children(node)))):
                stack.append((child, depth + 1, f"{path}/{i}"))
        return found

    def find(self, selector: dict, stop: Event, parent: Node | None = None,
             recipient: str = "", roots_only=False) -> list[Node]:
        roots = self.roots() if parent is None else self.children(parent)
        nodes = [(n, 0, "") for n in roots] if roots_only else self.walk(roots, stop)
        return [n for n, _, _ in nodes if matches(n, selector, recipient)]

    def one(self, selector: dict, stop: Event, parent: Node | None = None,
            recipient: str = "", roots_only=False) -> Node:
        nodes = self.find(selector, stop, parent, recipient, roots_only)
        if len(nodes) != 1:
            raise IntegrationError(f"화면 요소를 하나로 식별할 수 없습니다 ({len(nodes)}개). 연결 설정/열린 창을 확인해 주세요.")
        return nodes[0]

    def chat_controls(self, chat: Node, selectors: dict, stop: Event) -> tuple[Node, Node]:
        return (self.one(selectors["editor"], stop, chat),
                self.one(selectors["send_button"], stop, chat))

    def snapshot(self, stop: Event) -> dict:
        nodes = self.walk(self.roots(), stop)
        return {"platform": self.platform, "pid": self.pid,
                "note": "진단에는 화면에 공개된 이름이 포함됩니다. 메시지 입력 값은 별도로 수집하지 않습니다.",
                "nodes": [{**n.metadata(), "depth": depth, "path": path} for n, depth, path in nodes]}

    def read_value(self, node: Node) -> str:
        raise NotImplementedError

    def set_value(self, node: Node, value: str) -> None:
        raise NotImplementedError

    def enter_text(self, chat: Node, editor: Node, message: str, stop: Event) -> None:
        checkpoint(stop)
        self.set_value(editor, message)

    def close_chat(self, chat: Node, stop: Event) -> None:
        raise IntegrationError("대화창 닫기를 지원하지 않습니다.")

    def can_write(self, node: Node) -> bool:
        raise NotImplementedError

    def can_press(self, node: Node) -> bool:
        raise NotImplementedError

    def enabled(self, node: Node) -> bool:
        raise NotImplementedError

    def press(self, node: Node) -> None:
        raise NotImplementedError


    def photo_sheets(self, chat: Node) -> list[Node]:
        raise IntegrationError("이 운영체제는 사진 전송을 지원하지 않습니다.")

    def photo_clipboard(self, photo: Photo) -> AbstractContextManager[Callable[[], None] | None]:
        raise IntegrationError("이 운영체제는 사진 전송을 지원하지 않습니다.")

    def paste_photo(self, chat: Node, editor: Node) -> None:
        raise IntegrationError("이 운영체제는 사진 전송을 지원하지 않습니다.")

    def close(self) -> None:
        pass

    def refresh_node(self, node: Node) -> Node:
        return node
