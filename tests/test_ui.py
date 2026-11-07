import os
import time
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox
from kakaosender.ui import Window, apply_theme
from kakaosender.models import Plan


def settle(app, window):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if window.task is None and window.friends is not None:
            return
        time.sleep(0.005)
    raise AssertionError("UI task did not finish")


def test_search_select_and_async_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("kakaosender.ui.data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = Window(auto_connect=False)
    from kakaosender.test_support import FixtureBackend
    window.factory = lambda: FixtureBackend
    window.load_friends()
    window.chat_timer.stop()
    window.show()
    settle(app, window)
    assert window.friend_table.rowCount() == 11
    assert not window.live.isChecked()
    window.search.setText("김")
    window.select_visible(True)
    assert [friend.name for friend in window.selected()] == ["김민준"]
    window.message.setPlainText("테스트 👋\n두 번째 줄")
    assert window.start_button.isEnabled()
    plan = Plan(window.selected(), window.message.toPlainText(), "demo", False, 0)
    window.run_plan(plan)
    assert not window.message.isEnabled()
    settle(app, window)
    assert [result.state for result in window.results] == ["checked"]
    assert window.message.isEnabled()
    window.close()


@pytest.fixture
def sender(tmp_path, monkeypatch):
    monkeypatch.setattr("kakaosender.ui.data_dir", lambda: tmp_path)
    monkeypatch.setattr(Window, "check_connection", lambda self: None)
    app = QApplication.instance() or QApplication([])
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Base, QColor("#222222"))
    dark.setColor(QPalette.ColorRole.Text, QColor("#eeeeee"))
    app.setPalette(dark)
    apply_theme(app)
    window = Window(auto_connect=False)
    from kakaosender.test_support import FixtureBackend
    window.factory = lambda: FixtureBackend
    window.load_friends()
    window.chat_timer.stop()
    window.show()
    settle(app, window)
    yield app, window
    window.chat_timer.stop()
    if window.watch_task is not None:
        window.watch_task.stop.set()
        window.watch_task.wait()
        app.processEvents()
    if window.task is not None:
        window.stop()
        window.task.wait()
        app.processEvents()
    window.close()


def click_friend(window, row, column):
    item = window.friend_table.item(row, column)
    window.friend_table.scrollToItem(item)
    point = window.friend_table.visualItemRect(item).center()
    QTest.mouseClick(window.friend_table.viewport(), Qt.MouseButton.LeftButton, pos=point)


def test_row_checkbox_and_keyboard_toggle_once(sender):
    app, window = sender
    click_friend(window, 0, 1)
    assert [friend.name for friend in window.selected()] == ["김민준"]
    click_friend(window, 0, 0)
    assert not window.selected()
    QTest.keyClick(window.friend_table, Qt.Key.Key_Space)
    assert len(window.selected()) == 1
    QTest.keyClick(window.friend_table, Qt.Key.Key_Down)
    QTest.keyClick(window.friend_table, Qt.Key.Key_Space)
    assert len(window.selected()) == 2
    click_friend(window, 8, 1)
    click_friend(window, 8, 0)
    QTest.keyClick(window.friend_table, Qt.Key.Key_Space)
    assert len(window.selected()) == 2
    assert "선택 불가" in window.friend_table.item(8, 1).toolTip()
    window.set_busy(True)
    click_friend(window, 1, 1)
    assert len(window.selected()) == 2
    window.set_busy(False)


def test_filtered_selection_and_empty_state(sender):
    app, window = sender
    click_friend(window, 1, 1)
    window.search.setText("김")
    QTest.mouseClick(window.select_all, Qt.MouseButton.LeftButton)
    assert {friend.name for friend in window.selected()} == {"박서연", "김민준"}
    assert "2개" in window.selection_count.text()
    window.search.setText("없는 친구")
    assert window.empty_friends.isVisible()
    assert not window.friend_table.isVisible()
    assert not window.select_all.isEnabled()
    QTest.mouseClick(window.clear_all, Qt.MouseButton.LeftButton)
    assert not window.selected()
    window.search.clear()
    assert window.friend_table.isVisible()
    assert not window.empty_friends.isVisible()


def test_message_preview_and_native_controls(sender, monkeypatch):
    app, window = sender
    click_friend(window, 0, 1)
    text = "<b>그대로</b> 👋\n둘째 줄"
    window.message.setPlainText(text)
    assert window.message.toPlainText() == text
    assert not hasattr(window, "bubble")
    assert window.start_button.isEnabled()
    window.message.setPlainText("가" * 10001)
    assert not window.start_button.isEnabled()
    window.message.setPlainText(text)
    option = QStyleOptionSpinBox()
    window.interval.initStyleOption(option)
    rect = window.interval.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, window.interval)
    QTest.mouseClick(window.interval, Qt.MouseButton.LeftButton, pos=rect.center())
    assert window.interval.value() == 3
    # There is no demo selector; a connected fixture exposes the real-send toggle.
    assert not hasattr(window, "mode")
    window.set_busy(False)
    QTest.mouseClick(window.live, Qt.MouseButton.LeftButton)
    assert window.live.isChecked()
    assert "다음 화면" in window.send_hint.text()
    assert app.palette().color(QPalette.ColorRole.Base).name() == "#151515"
    window.resize(940, 700)
    window.history_toggle.click()
    app.processEvents()
    assert window.start_button.isVisible()
    assert window.rect().contains(window.start_button.mapTo(window, window.start_button.rect().bottomRight()))
    window.nav_buttons[1].click()
    assert window.tabs.currentIndex() == 1
    assert not window.advanced_panel.isVisible()
    window.advanced_toggle.click()
    assert window.profile_text.isVisible()


def test_photo_picker_preview_remove_and_photo_only_plan(sender, tmp_path, monkeypatch):
    from test_photos import photo_file
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QFileDialog, QPushButton
    app, window = sender
    path = photo_file(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(path)], ""))
    click_friend(window, 0, 1)
    QTest.mouseClick(window.photo_button, Qt.MouseButton.LeftButton)
    settle(app, window)
    assert len(window.photos) == 1
    assert window.photo_preview.isVisible()
    assert window.message.isVisible()
    assert window.start_button.isEnabled()
    assert not window.message.toPlainText()
    path.unlink()
    captured = []
    monkeypatch.setattr(window, "run_plan", captured.append)
    QTimer.singleShot(0, lambda: app.activeModalWidget().accept())
    window.preview()
    assert captured[0].photos == window.photos
    assert not captured[0].live
    remove = next(b for b in window.photo_preview.findChildren(QPushButton)
                  if b.accessibleName() == "사진 1 삭제")
    QTest.mouseClick(remove, Qt.MouseButton.LeftButton)
    assert not window.photos
    assert not window.start_button.isEnabled()
    assert window.message.isVisible()


def test_self_chat_is_selected_from_the_same_open_chat_list(sender):
    app, window = sender
    window.search.setText("나와의 채팅")
    window.select_visible(True)
    assert [chat.name for chat in window.selected()] == ["나와의 채팅"]
    assert not hasattr(window, "self_selection")
    window.message.setPlainText("나에게 테스트")
    assert window.start_button.isEnabled()
    assert "대화방 1개" in window.recipient_summary.text()
    window.clear_all.click()
    assert not window.selected()


def set_connected_list(window, friends):
    from kakaosender.models import FriendList
    window.on_friends(FriendList(tuple(friends), "open-session", True, session_pid=123))
    window.set_busy(False)


def test_auto_refresh_preserves_draft_photos_selection_and_original_handle(sender):
    from kakaosender.models import Friend, WindowBinding, FriendList
    from dataclasses import replace
    app, window = sender
    original = Friend("one", "본인 대화", window=WindowBinding(123, "window-one", object()))
    set_connected_list(window, [original])
    click_friend(window, 0, 1)
    window.message.setPlainText("작성 중인 메시지")
    window.live.setChecked(True)
    refreshed = replace(original, window=WindowBinding(123, "window-one", object()))
    extra = Friend("two", "새 대화방")
    window.on_auto_chats(FriendList((refreshed, extra), "open-session", True, session_pid=123))
    assert window.selected() == (original,)
    assert window.selected()[0].window.native is original.window.native
    assert window.message.toPlainText() == "작성 중인 메시지"
    assert window.live.isChecked() and window.message.isEnabled()
    assert window.friend_table.rowCount() == 2


def test_auto_refresh_removes_closed_chat_without_selecting_replacement(sender):
    from kakaosender.models import Friend, FriendList
    app, window = sender
    set_connected_list(window, [Friend("old", "같은 제목")])
    click_friend(window, 0, 1)
    window.message.setPlainText("보존할 초안")
    window.live.setChecked(True)
    window.on_auto_chats(FriendList((Friend("new", "같은 제목"),), "open-session", True, session_pid=123))
    assert not window.selected()
    assert not window.live.isChecked() and not window.start_button.isEnabled()
    assert window.message.toPlainText() == "보존할 초안"


def test_auto_refresh_failure_clears_stale_targets_without_modal_or_draft_loss(sender):
    from kakaosender.models import Friend
    app, window = sender
    set_connected_list(window, [Friend("old", "본인 대화")])
    click_friend(window, 0, 1)
    window.message.setPlainText("보존할 초안")
    window.on_auto_chat_error("권한 확인 필요")
    assert window.friends is None and not window.selected()
    assert window.empty_friends.text() == "권한 확인 필요"
    assert window.message.toPlainText() == "보존할 초안"
    assert not window.start_button.isEnabled()


def test_timer_detects_new_chat_without_refresh_click_and_does_not_lock_editor(sender, monkeypatch):
    from kakaosender.models import Friend, FriendList
    from threading import Event
    app, window = sender
    set_connected_list(window, [])
    entered, release = Event(), Event()
    class Backend:
        def __init__(self, driver, profile, catalog=None): pass
        def list_friends(self, stop):
            entered.set()
            release.wait(2)
            return FriendList((Friend("new", "새로 연 대화방"),), "open-session", True, session_pid=123)
        def close(self): pass
    monkeypatch.setattr("kakaosender.ui.native_driver", lambda: object())
    monkeypatch.setattr("kakaosender.ui.ConversationBackend", Backend)
    window.chat_timer.setInterval(10)
    window.chat_timer.start()
    deadline = time.monotonic() + 2
    while not entered.is_set() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert entered.is_set()
    assert window.message.isEnabled() and window.photo_button.isEnabled()
    window.chat_timer.stop()
    release.set()
    while window.watch_task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert window.friend_table.item(0, 1).text() == "새로 연 대화방"
    assert window.task is None


def test_background_poll_is_paused_during_sending_or_confirmation(sender, monkeypatch):
    app, window = sender
    set_connected_list(window, [])
    monkeypatch.setattr("kakaosender.ui.native_driver", lambda: pytest.fail("must not poll"))
    window.task = object()
    window.poll_open_chats()
    assert window.watch_task is None
    window.task = None
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: object()))
    window.poll_open_chats()
    assert window.watch_task is None


def test_completed_results_return_to_composer_keeps_message_photo_and_targets(sender, tmp_path):
    from test_photos import photo_file
    app, window = sender
    click_friend(window, 0, 1)
    window.message.setPlainText("돌아와도 남아 있는 본문")
    window.add_photo_paths([photo_file(tmp_path)])
    settle(app, window)
    selected, photos = window.selected(), window.photos
    window.resize(940, 700)
    window.run_plan(Plan(selected, window.message.toPlainText(), "demo", False, 0, photos))
    settle(app, window)
    assert window.preview_stack.currentIndex() == 1
    assert window.back_to_composer.isVisible() and window.back_to_composer.isEnabled()
    assert window.rect().contains(window.back_to_composer.mapTo(window, window.back_to_composer.rect().bottomRight()))
    QTest.mouseClick(window.back_to_composer, Qt.MouseButton.LeftButton)
    assert window.preview_stack.currentIndex() == 0 and not window.history_toggle.isChecked()
    assert window.message.toPlainText() == "돌아와도 남아 있는 본문"
    assert window.photos == photos and window.selected() == selected
    assert window.message.isEnabled()
    window.history_toggle.click()
    assert window.start_button.text() == "메시지 작성으로 돌아가기"
    window.start_button.click()
    assert window.preview_stack.currentIndex() == 0
    window.toggle_history(True)
    window.nav_buttons[0].click()
    assert window.preview_stack.currentIndex() == 0


def test_results_can_be_left_even_without_selected_targets_or_message(sender):
    app, window = sender
    window.clear_recipients()
    window.message.clear()
    window.toggle_history(True)
    assert window.start_button.isEnabled()
    window.start_button.click()
    assert window.preview_stack.currentIndex() == 0
    assert not window.start_button.isEnabled()


def test_connection_failure_has_no_demo_list_or_modal(tmp_path, monkeypatch):
    from kakaosender.models import IntegrationError, Friend, FriendList
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr('kakaosender.ui.data_dir', lambda: tmp_path)
    monkeypatch.setattr(Window, 'check_connection', lambda self: None)
    def unavailable():
        raise IntegrationError('손쉬운 사용 권한을 허용해 주세요.')
    monkeypatch.setattr('kakaosender.ui.native_driver', unavailable)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: pytest.fail('connection failures must be inline'))
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.chat_timer.stop()
    window.show()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if window.task is None and window.connection_badge.text() == '연결 필요': break
        time.sleep(.01)
    assert not hasattr(window, 'mode')
    assert window.friends is None and window.friend_table.rowCount() == 0
    assert '권한' in window.empty_friends.text()
    assert not window.live.isEnabled() and not window.start_button.isEnabled()
    window.on_friends(FriendList((Friend('actual', '실제 연결 대상'),), 'actual', True))
    window.set_busy(False)
    assert window.friend_table.rowCount() == 1
    assert window.connection_badge.text() == '카카오톡 연결됨'
    assert not window.live.isChecked()
    window.close()


def test_colored_result_cards_keep_user_text_literal(sender):
    from kakaosender.models import Friend, Result
    app, window = sender
    window.on_result(Result(Friend('literal', '<b>대화방</b>'), 'failed', '<img src="bad">\n확인 필요'))
    plain = window.log.toPlainText()
    assert '<b>대화방</b>' in plain and '<img src="bad">' in plain
    assert '실패 · 중지' in plain and '확인 필요' in plain
