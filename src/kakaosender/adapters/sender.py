from __future__ import annotations

from threading import Event
import time
from .accessibility import Driver, Node
from ..attachments import Photo, validate_photos
from ..models import ActionOutcomeUnknown, Friend, IntegrationError, UncertainSend, checkpoint


class ChatSender:
    """Shared text/photo submission; concrete backends bind the selected window."""
    is_demo = False

    def _scope(self, stop: Event) -> str:
        raise NotImplementedError

    def _chat(self, friend: Friend, stop: Event) -> Node:
        raise NotImplementedError

    def __init__(self, driver: Driver, profile: dict, expected_pid: int | None = None):
        self.driver = driver
        self.profile = profile
        self.selectors = profile.get("selectors", {})
        self.expected_pid = expected_pid
        self.prepared: str | None = None

    def _check_scope(self, scope: str, stop: Event) -> None:
        if self._scope(stop) != scope:
            raise IntegrationError("로그인된 사용자 표시가 달라졌습니다. 목록을 새로 불러와 주세요.")

    def _controls(self, friend: Friend, stop: Event):
        chat = self._chat(friend, stop)
        editor = self.driver.one(self.selectors["editor"], stop, chat)
        button = self.driver.one(self.selectors["send_button"], stop, chat)
        if not self.driver.can_write(editor) or not self.driver.can_press(button):
            raise IntegrationError("입력창 쓰기 또는 전송 버튼의 접근성 동작이 지원되지 않습니다.")
        return editor, button

    def send(self, friend: Friend, message: str, scope: str, stop: Event) -> None:
        if self.prepared != friend.key:
            raise IntegrationError("대상 확인을 먼저 실행해야 합니다.")
        checkpoint(stop)
        self._check_scope(scope, stop)
        editor, _ = self._controls(friend, stop)
        if self.driver.read_value(editor):
            raise IntegrationError("입력창 내용이 변경되었습니다.")
        self.driver.enter_text(self._chat(friend, stop), editor, message, stop)
        checkpoint(stop)
        self._check_scope(scope, stop)
        editor, button = self._controls(friend, stop)
        if self.driver.read_value(editor).replace("\r\n", "\n") != message.replace("\r\n", "\n"):
            raise IntegrationError("입력된 내용이 원문과 다릅니다. 대화창을 직접 확인해 주세요.")
        deadline = time.monotonic() + 3
        while not self.driver.enabled(button):
            checkpoint(stop)
            if time.monotonic() >= deadline:
                raise IntegrationError("입력 후 전송 버튼이 활성화되지 않았습니다. 전송하지 않았습니다.")
            stop.wait(.05)
            self._check_scope(scope, stop)
            editor, button = self._controls(friend, stop)
            if self.driver.read_value(editor).replace("\r\n", "\n") != message.replace("\r\n", "\n"):
                raise IntegrationError("전송 대기 중 입력 내용이 변경됐습니다. 전송하지 않았습니다.")
        checkpoint(stop)
        try:
            self.driver.press(button)
        except ActionOutcomeUnknown:
            # KakaoTalk can return an AX error after applying the action.
            # Check the original target's postcondition, without a second press.
            pass
        self.prepared = None
        deadline = time.monotonic() + 3
        # After pressing, cancellation cannot prove non-delivery. Verify clearing
        # with a fresh non-cancelled event, then let the batch stop.
        verify = Event()
        while time.monotonic() < deadline:
            editor, _ = self._controls(friend, verify)
            if self.driver.read_value(editor) == "":
                return
            time.sleep(0.1)
        raise UncertainSend("전송 후 입력창 비움을 확인하지 못했습니다. 카카오톡에서 직접 확인해 주세요.")

    def validate_photos(self, photos: tuple[Photo, ...]) -> None:
        validate_photos(photos)
        if not self.driver.supports_photos:
            raise IntegrationError("사진 전송은 현재 macOS 카카오톡에서 지원합니다.")

    def send_photo(self, friend: Friend, photo: Photo, scope: str, stop: Event) -> None:
        self.validate_photos((photo,))
        if self.prepared != friend.key:
            raise IntegrationError("대상 확인을 먼저 실행해야 합니다.")
        checkpoint(stop)
        self._check_scope(scope, stop)
        chat = self._chat(friend, stop)
        editor, _ = self._controls(friend, stop)
        if self.driver.read_value(editor) or self.driver.photo_sheets(chat):
            raise IntegrationError("대화창에 작성 중인 내용이나 첨부 창이 있습니다. 먼저 직접 정리해 주세요.")
        try:
            with self.driver.photo_clipboard(photo) as verify_clipboard:
                checkpoint(stop)
                self._check_scope(scope, stop)
                if self._chat(friend, stop).key != chat.key:
                    raise IntegrationError("사진을 보낼 대화창이 변경되었습니다.")
                if verify_clipboard is not None:
                    verify_clipboard()
                self.driver.paste_photo(chat, editor)
                if verify_clipboard is not None:
                    verify_clipboard()
                sheet = None
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    checkpoint(stop)
                    sheets = self.driver.photo_sheets(chat)
                    if len(sheets) > 1:
                        raise UncertainSend("사진 확인 창이 여러 개입니다. 카카오톡에서 직접 확인해 주세요.")
                    if sheets:
                        sheet = sheets[0]
                        break
                    stop.wait(0.1)
                if sheet is None:
                    # Some clients may send immediately. Never infer success or paste again.
                    raise UncertainSend("사진 확인 창을 확인하지 못했습니다. 전송 여부를 직접 확인해 주세요. 자동 재전송하지 않습니다.")
                nodes = [node for node, _, _ in self.driver.walk([sheet], stop)]
                buttons = [node for node in nodes if node.role == "AXButton" and node.name in {"전송", "Send"}]
                if len(buttons) != 1 or not any(node.role == "AXImage" for node in nodes):
                    raise UncertainSend("사진 미리보기와 전송 버튼을 유일하게 확인하지 못했습니다.")
                self._check_scope(scope, stop)
                current = self._chat(friend, stop)
                sheets = self.driver.photo_sheets(current)
                if current.key != chat.key or len(sheets) != 1 or sheets[0].key != sheet.key:
                    raise UncertainSend("사진 확인 창이 변경되었습니다. 카카오톡에서 직접 확인해 주세요.")
                checkpoint(stop)
                try:
                    self.driver.press(buttons[0])
                except ActionOutcomeUnknown:
                    pass
                deadline = time.monotonic() + 4
                verify = Event()
                while time.monotonic() < deadline:
                    current = self._chat(friend, verify)
                    if current.key != chat.key:
                        raise UncertainSend("전송 후 대화창이 변경되었습니다.")
                    if not self.driver.photo_sheets(current):
                        editor, _ = self._controls(friend, verify)
                        if not self.driver.read_value(editor):
                            return
                    time.sleep(0.1)
                raise UncertainSend("사진 전송 후 확인 창이 닫히지 않았습니다. 자동 재전송하지 않습니다.")
        finally:
            self.prepared = None

    def close(self) -> None:
        self.driver.close()
