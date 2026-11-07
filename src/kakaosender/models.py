from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Protocol
import hashlib
import unicodedata
from .attachments import Photo, validate_photos


class IntegrationError(RuntimeError):
    """The client cannot be identified or does not expose required controls."""


class Cancelled(RuntimeError):
    pass


class UncertainSend(RuntimeError):
    """A send may have happened. Never retry automatically."""


class ActionOutcomeUnknown(IntegrationError):
    """A native action was invoked but its return code cannot prove the outcome."""


def canonical(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def checkpoint(stop: Event) -> None:
    if stop.is_set():
        raise Cancelled("사용자가 중지했습니다.")


@dataclass(frozen=True)
class WindowBinding:
    pid: int
    key: str
    native: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class ConversationBinding:
    main: WindowBinding
    table_key: str
    table_native: object = field(repr=False, compare=False)
    row_key: str
    row_native: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class Friend:
    key: str
    name: str
    selectable: bool = True
    note: str = ""
    window: WindowBinding | None = field(default=None, repr=False, compare=False)
    conversation: ConversationBinding | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class FriendList:
    friends: tuple[Friend, ...]
    scope: str
    complete: bool
    note: str = ""
    session_pid: int | None = None
    catalog: WindowBinding | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Plan:
    recipients: tuple[Friend, ...]
    message: str
    scope: str
    live: bool = False
    interval: float = 2.0
    photos: tuple[Photo, ...] = ()

    def validate(self) -> None:
        if not self.recipients:
            raise ValueError("대화방을 하나 이상 선택해 주세요.")
        validate_photos(self.photos)
        if not self.message.strip() and not self.photos:
            raise ValueError("메시지를 입력하거나 사진을 추가해 주세요.")
        if len(self.message) > 10000:
            raise ValueError("시제품은 메시지 10,000자까지 지원합니다.")
        if not 0 <= self.interval <= 3600:
            raise ValueError("발송 간격이 올바르지 않습니다.")
        if len({f.key for f in self.recipients}) != len(self.recipients):
            raise ValueError("발송 대상이 중복되었습니다.")
        if any(not f.selectable for f in self.recipients):
            raise ValueError("구분할 수 없는 대화방이 포함되었습니다.")


@dataclass(frozen=True)
class Result:
    friend: Friend
    state: str
    detail: str


class Backend(Protocol):
    is_demo: bool

    def list_friends(self, stop: Event) -> FriendList: ...
    def prepare(self, friend: Friend, scope: str, stop: Event) -> None: ...
    def send(self, friend: Friend, message: str, scope: str, stop: Event) -> None: ...
    def validate_photos(self, photos: tuple[Photo, ...]) -> None: ...
    def send_photo(self, friend: Friend, photo: Photo, scope: str, stop: Event) -> None: ...
    def finish_recipient(self, friend: Friend, scope: str, stop: Event) -> None: ...
    def close(self) -> None: ...
