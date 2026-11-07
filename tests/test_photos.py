from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QColor

from kakaosender.attachments import load_photo, validate_photos
from kakaosender.adapters.accessibility import Node
from kakaosender.models import Friend, Plan, UncertainSend, IntegrationError
from kakaosender.engine import execute
from kakaosender.storage import Journal
from test_sender import FakeDriver, FastEvent, configured


def photo_file(tmp_path: Path, name: str = "photo.png", color: str = "#75b3d9") -> Path:
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    path = tmp_path / name
    assert image.save(str(path))
    return path


def test_photos_are_immutable_and_reject_bad_input(tmp_path):
    path = photo_file(tmp_path)
    photo = load_photo(path)
    path.unlink()
    assert photo.width == 120 and photo.height == 80
    assert QImage.fromData(photo.content).pixelColor(0, 0).name() == "#75b3d9"
    bad = tmp_path / "bad.png"
    bad.write_text("this is not an image")
    with pytest.raises(ValueError):
        load_photo(bad)
    with pytest.raises(ValueError, match="중복"):
        validate_photos((photo, photo))
    with pytest.raises(ValueError, match="10장"):
        validate_photos((photo,) * 11)
    Plan((Friend("a", "가"),), "", "demo", photos=(photo,)).validate()


@pytest.mark.parametrize("extension", ["jpg", "png", "webp", "bmp"])
def test_supported_photo_formats(tmp_path, extension):
    photo = load_photo(photo_file(tmp_path, "photo." + extension))
    assert photo.content.startswith(b"\x89PNG")


class PhotoBackend:
    is_demo = False

    def __init__(self):
        self.sent = []
        self.prepared = []
        self.fail_photo = None

    def finish_recipient(self, friend, scope, stop):
        pass

    def validate_photos(self, photos):
        validate_photos(photos)

    def prepare(self, friend, scope, stop):
        self.prepared.append(friend.key)

    def send(self, friend, message, scope, stop):
        self.sent.append((friend.key, "text", message))

    def send_photo(self, friend, photo, scope, stop):
        self.sent.append((friend.key, "photo", photo.fingerprint))
        if self.fail_photo == photo.fingerprint:
            raise UncertainSend("photo completion unknown")


def test_photo_dry_run_and_partial_retry(tmp_path):
    first = load_photo(photo_file(tmp_path, "one.png"))
    second = load_photo(photo_file(tmp_path, "two.png", "#febc40"))
    backend = PhotoBackend()
    journal = Journal(tmp_path / "journal.db")
    friends = (Friend("a", "가"), Friend("b", "나"))
    try:
        plan = Plan(friends, "안녕", "owner", False, 0, (first, second))
        assert [r.state for r in execute(plan, backend, journal, Event(), lambda r: None)] == ["checked", "checked"]
        assert not backend.sent
        backend.fail_photo = second.fingerprint
        plan = Plan(friends, "안녕", "owner", True, 0, (first, second))
        result = execute(plan, backend, journal, Event(), lambda r: None)
        assert [r.state for r in result] == ["uncertain"]
        assert [part[1] for part in backend.sent] == ["text", "photo", "photo"]
        backend.fail_photo = None
        backend.sent.clear()
        result = execute(plan, backend, journal, Event(), lambda r: None)
        assert [r.state for r in result] == ["duplicate", "submitted"]
        assert {part[0] for part in backend.sent} == {"b"}
        # The same previewed bytes, not the filename or surrounding message, identify a photo.
        assert not journal.reserve("owner", "a", "changed text", first.fingerprint)
        assert Journal.identity("owner", "a", first.fingerprint) != Journal.identity("owner", "a", "", first.fingerprint)
    finally:
        journal.close()


def test_photo_only_and_unsupported_preflight(tmp_path):
    photo = load_photo(photo_file(tmp_path))
    backend = PhotoBackend()
    journal = Journal(tmp_path / "journal.db")
    try:
        plan = Plan((Friend("a", "가"),), "", "owner", True, 0, (photo,))
        assert execute(plan, backend, journal, Event(), lambda r: None)[0].state == "submitted"
        assert [part[1] for part in backend.sent] == ["photo"]
        driver = FakeDriver()
        with pytest.raises(IntegrationError, match="macOS"):
            execute(plan, configured(driver), journal, Event(), lambda r: None)
        assert not driver.writes and not driver.presses
    finally:
        journal.close()


class PhotoDriver(FakeDriver):
    supports_photos = True

    def __init__(self):
        super().__init__()
        self.sheet = False
        self.restored = False
        self.pasted = 0
        self.change_chat = False
        self.extra_button = False

    def children(self, node):
        if node.key == "photo-sheet":
            nodes = [Node("AXImage", "", "", None, "image"), Node("AXButton", "전송", "", None, "photo-send")]
            if self.extra_button:
                nodes.append(Node("AXButton", "전송", "", None, "second-send"))
            return nodes
        return super().children(node)

    def photo_sheets(self, chat):
        return [Node("AXSheet", "사진", "", None, "photo-sheet")] if self.sheet else []

    @contextmanager
    def photo_clipboard(self, photo):
        try:
            yield
        finally:
            self.restored = True

    def paste_photo(self, chat, editor):
        self.pasted += 1
        self.sheet = True
        if self.change_chat:
            self.chat = "다른 사람"

    def press(self, node):
        super().press(node)
        if node.key == "photo-send":
            self.sheet = False


def test_photo_confirmation_is_scoped_and_pressed_once(tmp_path):
    photo = load_photo(photo_file(tmp_path))
    driver = PhotoDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    backend.send_photo(friend, photo, listing.scope, FastEvent())
    assert driver.pasted == 1
    assert driver.presses == ["photo-send"]
    assert driver.restored


@pytest.mark.parametrize("condition", ["extra_button", "change_chat"])
def test_photo_ambiguous_or_changed_target_never_confirms(tmp_path, condition):
    photo = load_photo(photo_file(tmp_path))
    driver = PhotoDriver()
    setattr(driver, condition, True)
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    with pytest.raises((IntegrationError, UncertainSend)):
        backend.send_photo(friend, photo, listing.scope, FastEvent())
    assert not driver.presses
    assert driver.restored


def test_existing_attachment_is_not_replaced(tmp_path):
    photo = load_photo(photo_file(tmp_path))
    driver = PhotoDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    driver.sheet = True
    with pytest.raises(IntegrationError, match="첨부"):
        backend.send_photo(friend, photo, listing.scope, FastEvent())
    assert driver.pasted == 0


def test_missing_confirmation_is_uncertain_without_retry(tmp_path, monkeypatch):
    photo = load_photo(photo_file(tmp_path))
    driver = PhotoDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    def paste(chat, editor):
        driver.pasted += 1
    driver.paste_photo = paste
    import itertools
    ticks = itertools.count(0, 10)
    monkeypatch.setattr("kakaosender.adapters.sender.time.monotonic", lambda: next(ticks))
    with pytest.raises(UncertainSend, match="확인 창"):
        backend.send_photo(friend, photo, listing.scope, FastEvent())
    assert driver.pasted == 1
    assert not driver.presses
    assert driver.restored


@pytest.mark.parametrize("changed", [False, True])
def test_clipboard_restore_preserves_newer_user_copy(tmp_path, monkeypatch, changed):
    from types import SimpleNamespace
    import sys
    from kakaosender.adapters.macos import MacDriver
    photo = load_photo(photo_file(tmp_path))
    class Item:
        def __init__(self, data=None): self.data = data or {}
        def types(self): return list(self.data)
        def dataForType_(self, kind): return self.data.get(kind)
        def setData_forType_(self, data, kind): self.data[kind] = data; return True
        @classmethod
        def alloc(cls): return cls()
        def init(self): return self
    class Board:
        def __init__(self): self.items = [Item({"text": b"original"})]; self.count = 1
        def changeCount(self): return self.count
        def pasteboardItems(self): return self.items
        def clearContents(self): self.items = []; self.count += 1; return self.count
        def writeObjects_(self, items): self.items = list(items); return True
    board = Board()
    image = SimpleNamespace(initWithData_=lambda data: Item({"image": data}))
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSImage=SimpleNamespace(alloc=lambda: image),
        NSPasteboard=SimpleNamespace(generalPasteboard=lambda: board), NSPasteboardItem=Item))
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSData=SimpleNamespace(dataWithBytes_length_=lambda data, length: data)))
    driver = object.__new__(MacDriver)
    with pytest.raises(RuntimeError):
        with driver.photo_clipboard(photo):
            assert "image" in board.items[0].data
            if changed:
                board.clearContents()
                board.writeObjects_([Item({"text": b"new user copy"})])
            raise RuntimeError("send failed")
    assert board.items[0].data["text"] == (b"new user copy" if changed else b"original")


def test_clipboard_changed_during_paste_never_confirms(tmp_path):
    photo = load_photo(photo_file(tmp_path))
    driver = PhotoDriver()
    @contextmanager
    def clipboard(photo):
        def verify():
            if driver.pasted:
                raise IntegrationError("clipboard changed")
        yield verify
    driver.photo_clipboard = clipboard
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    with pytest.raises(IntegrationError, match="clipboard changed"):
        backend.send_photo(friend, photo, listing.scope, FastEvent())
    assert driver.pasted == 1
    assert not driver.presses


@pytest.mark.parametrize('applied', [True, False])
def test_photo_action_error_observes_original_sheet_without_retry(tmp_path, monkeypatch, applied):
    import itertools
    from kakaosender.models import ActionOutcomeUnknown
    photo = load_photo(photo_file(tmp_path))
    driver = PhotoDriver()
    backend = configured(driver)
    listing = backend.list_friends(FastEvent())
    friend = listing.friends[0]
    backend.prepare(friend, listing.scope, FastEvent())
    def press(node):
        driver.presses.append(node.key)
        if applied: driver.sheet = False
        raise ActionOutcomeUnknown('AX returned an error')
    driver.press = press
    ticks = itertools.count()
    monkeypatch.setattr('kakaosender.adapters.sender.time.monotonic', lambda: next(ticks))
    if applied:
        backend.send_photo(friend, photo, listing.scope, FastEvent())
    else:
        with pytest.raises(UncertainSend):
            backend.send_photo(friend, photo, listing.scope, FastEvent())
    assert driver.pasted == 1 and driver.presses == ['photo-send']
