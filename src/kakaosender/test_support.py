"""Synthetic backend injected only by automated/package tests."""
from __future__ import annotations

from threading import Event
from .attachments import Photo, validate_photos
from .models import Friend, FriendList, IntegrationError, checkpoint


class FixtureBackend:
    is_demo = True
    scope = "demo"

    def list_friends(self, stop: Event) -> FriendList:
        checkpoint(stop)
        names = ["김민준", "박서연", "이도윤", "정하린", "최지우", "윤서준", "한수빈", "오지호"]
        friends = [Friend(f"fixture-{i}", name, note="예시 대화방") for i, name in enumerate(names)]
        friends += [Friend("duplicate-1", "김지민", False, "동일한 제목 · 선택 불가"),
                    Friend("duplicate-2", "김지민", False, "동일한 제목 · 선택 불가")]
        friends.append(Friend("fixture-open-self", "나와의 채팅", note="예시 대화방"))
        return FriendList(tuple(friends), self.scope, True, "예시 대화방 11개 · 실제 카카오톡에 연결하지 않습니다.")

    def prepare(self, friend: Friend, scope: str, stop: Event) -> None:
        checkpoint(stop)
        if scope != self.scope or not friend.selectable:
            raise IntegrationError("목록을 새로 불러와 주세요.")

    def send(self, friend: Friend, message: str, scope: str, stop: Event) -> None:
        raise IntegrationError("자체 검사는 메시지를 보내지 않습니다.")

    def validate_photos(self, photos: tuple[Photo, ...]) -> None:
        validate_photos(photos)

    def send_photo(self, friend: Friend, photo: Photo, scope: str, stop: Event) -> None:
        raise IntegrationError("자체 검사는 사진을 보내지 않습니다.")

    def close(self) -> None:
        pass

    def finish_recipient(self, friend: Friend, scope: str, stop: Event) -> None:
        pass
