from __future__ import annotations

import csv
from html import escape
import json
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QFont, QDesktopServices, QColor, QPalette, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QTextEdit, QProgressBar, QPushButton, QSplitter,
    QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QScrollArea, QSizePolicy, QToolButton, QStackedWidget, QGridLayout,
)

from .adapters import native_driver
from .profiles import PROFILE_FIELDS, empty_profile
from .adapters.conversations import ConversationBackend
from .engine import execute
from .models import FriendList, Plan, Result, Cancelled, checkpoint
from .attachments import Photo, PHOTO_FILTER, MAX_PHOTOS, load_photo, validate_photos
from .storage import Journal, data_dir
from .ui_widgets import FriendTable, VisibleCheckBox, VisibleComboBox, VisibleSpinBox, navigation_icon


STYLE = """
QWidget { color: #eeeeee; font-size: 13px; }
QMainWindow, QDialog, QWidget#workspace { background: #191919; }
QLabel { background: transparent; }
QLabel#headline { font-size: 23px; font-weight: 700; }
QLabel#section { font-size: 18px; font-weight: 600; }
QLabel#muted, QLabel#chatHint { color: #929292; font-size: 12px; }
QLabel#count { color: #dedede; font-size: 12px; }
QLabel#status { color: #777777; font-size: 11px; padding: 5px 18px; background: #202020; border-top: 1px solid #303030; }
QFrame#rail { background: #2a2a2a; border-right: 1px solid #363636; }
QFrame#friendsPane { background: #222222; border: 0; }
QFrame#chatCanvas, QFrame#draftCard, QFrame#historyPage { background: #151515; border: 0; }
QFrame#card, QWidget#connectionPage { background: #1b1b1b; border: 0; }
QFrame#sendActions { background: #222222; border-top: 1px solid #333333; }
QFrame#history { background: #222222; border-top: 1px solid #303030; }
QLabel#connectionBadge { color: #888888; font-size: 11px; padding: 0; }
QLabel#connectionBadge[state="waiting"] { color: #c7ad70; }
QLabel#connectionBadge[state="connected"] { color: #999999; }
QPushButton { background: #2b2b2b; color: #dddddd; border: 1px solid #3b3b3b; border-radius: 8px; padding: 8px 12px; }
QPushButton:hover { background: #363636; border-color: #515151; }
QPushButton:pressed { background: #404040; }
QPushButton:focus, QToolButton:focus { border: 1px solid #9c9151; }
QPushButton:disabled { color: #666666; background: #292929; border-color: #303030; }
QPushButton#primary { background: #fee500; color: #191919; border: 0; border-radius: 8px; font-weight: 700; padding: 10px 22px; }
QPushButton#primary:hover { background: #edda24; }
QPushButton#primary:disabled { background: #303030; color: #686868; }
QPushButton#textButton { background: transparent; border: 0; color: #999999; padding: 5px 4px; font-size: 12px; }
QPushButton#textButton:hover { color: #eeeeee; background: #303030; }
QPushButton#attach { background: transparent; border: 0; color: #cccccc; font-size: 25px; padding: 0; }
QPushButton#attach:hover { background: #363636; }
QPushButton#stop { color: #ef9393; }
QToolButton#nav { border: 1px solid transparent; border-radius: 10px; padding: 8px; background: transparent; }
QToolButton#nav:hover { background: #353535; }
QToolButton#nav:checked { background: #393939; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox { background: #252525; color: #eeeeee; border: 1px solid #3a3a3a; border-radius: 8px; padding: 8px; selection-background-color: #6b6022; selection-color: #ffffff; }
QTextEdit#resultLog { background: #151515; border: 0; padding: 0; }
QLineEdit#search { background: #303030; border: 0; border-radius: 8px; padding: 10px 12px; }
QLineEdit:focus { border: 1px solid #626262; }
QPlainTextEdit#message { background: #151515; border: 0; border-radius: 0; padding: 0; font-size: 16px; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #292929; color: #eeeeee; selection-background-color: #414141; selection-color: #ffffff; }
QSpinBox { background: #292929; border: 0; padding: 6px; }
QSpinBox::up-button, QSpinBox::down-button { border: 0; width: 18px; background: #333333; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; border-top-right-radius: 6px; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; border-bottom-right-radius: 6px; }
QCheckBox { color: #b8b8b8; spacing: 8px; padding: 2px 0; }
QCheckBox:disabled { color: #666666; }
QCheckBox::indicator { width: 22px; height: 22px; background: transparent; border: 0; }
QTableWidget, QTreeWidget { background: #222222; color: #eeeeee; border: 0; selection-background-color: #343434; selection-color: #eeeeee; outline: 0; }
QHeaderView::section { background: #292929; color: #aaaaaa; border: 0; padding: 8px; }
QTabWidget::pane { border: 0; }
QSplitter::handle { background: #333333; width: 1px; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
QScrollBar::handle:vertical { background: #484848; border-radius: 2px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { border: 0; background: #303030; border-radius: 2px; height: 3px; }
QProgressBar::chunk { background: #b8a92a; border-radius: 2px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#151515", QPalette.ColorRole.WindowText: "#eeeeee",
        QPalette.ColorRole.Base: "#151515", QPalette.ColorRole.AlternateBase: "#252525",
        QPalette.ColorRole.Text: "#eeeeee", QPalette.ColorRole.Button: "#151515",
        QPalette.ColorRole.ButtonText: "#eeeeee", QPalette.ColorRole.Highlight: "#6b6022",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: "#777777",
        QPalette.ColorRole.ToolTipBase: "#151515", QPalette.ColorRole.ToolTipText: "#eeeeee",
    }.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#777777"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#777777"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Malgun Gothic" if sys.platform == "win32" else "Apple SD Gothic Neo", 11))


STATES = {"checked": "확인 완료", "submitted": "전송 실행", "duplicate": "중복 건너뜀",
          "failed": "실패 · 중지", "uncertain": "결과 미확정 · 중지", "cancelled": "중지"}


RESULT_COLORS = {
    "checked": ("#202020", "#a9bac9"),
    "submitted": ("#202020", "#a9c8b5"),
    "duplicate": ("#202020", "#aaaaaa"),
    "failed": ("#202020", "#e9a0a0"),
    "uncertain": ("#202020", "#d6bc78"),
    "cancelled": ("#202020", "#aaaaaa"),
}

class Task(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.stop = Event()

    def run(self):
        try:
            self.done.emit(self.fn(self.stop, self.progress.emit))
        except Cancelled:
            self.failed.emit("작업을 중지했습니다.")
        except Exception as exc:
            self.failed.emit(str(exc))


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def button(text, callback, name=""):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.clicked.connect(callback)
    return widget


def card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)
    return frame, layout


class Window(QMainWindow):
    def __init__(self, auto_connect: bool = True):
        super().__init__()
        self.setWindowTitle("Kakao Friend Sender · 메시지 보내기")
        self.resize(1120, 800)
        self.setMinimumSize(940, 700)
        self.task: Task | None = None
        self.watch_task: Task | None = None
        self._close_pending = False
        self.friends: FriendList | None = None
        self.results: list[Result] = []
        self.photos: tuple[Photo, ...] = ()
        self.snapshot_data = None
        self.profile_path = data_dir() / f"profile-{sys.platform}.json"
        self.profile = empty_profile(sys.platform)
        if self.profile_path.exists():
            try:
                self.profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        root = QWidget()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(68)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(10, 24, 10, 18)
        nav.setSpacing(18)
        self.nav_buttons = []
        for index, (text, icon) in enumerate([("보내기", "friends"), ("연결 설정", "settings")]):
            item = QToolButton()
            item.setObjectName("nav")
            item.setText(text)
            item.setIcon(navigation_icon(icon))
            item.setIconSize(QSize(24, 24))
            item.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            item.setToolTip(text)
            item.setAccessibleName(text)
            item.setCheckable(True)
            item.setAutoExclusive(True)
            item.setFixedSize(48, 48)
            item.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            if index == 1:
                nav.addStretch()
            nav.addWidget(item)
            self.nav_buttons.append(item)
        self.nav_buttons[0].setChecked(True)
        shell.addWidget(rail)
        content = QWidget()
        content.setObjectName("workspace")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.connection_badge = label("연결 확인 중", "connectionBadge")
        self.connection_badge.setProperty("state", "waiting")
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        outer.addWidget(self.tabs, 1)
        self._sender_tab()
        self._setup_tab()
        self.tabs.currentChanged.connect(self.page_changed)
        self.status = label("카카오톡 연결을 확인하고 있습니다.", "status")
        self.status.setMinimumHeight(26)
        outer.addWidget(self.status)
        shell.addWidget(content, 1)
        self.setCentralWidget(root)
        self.chat_timer = QTimer(self)
        self.chat_timer.setInterval(2000)
        self.chat_timer.timeout.connect(self.poll_open_chats)
        if auto_connect:
            self.chat_timer.start()
            QTimer.singleShot(0, self.load_friends)
            if sys.platform == "darwin":
                QTimer.singleShot(0, self.check_connection)

    def page_changed(self, index: int) -> None:
        self.nav_buttons[index].setChecked(True)
        self.setWindowTitle("Kakao Friend Sender · " + ("메시지 보내기" if index == 0 else "연결 설정"))

    def navigate(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)
        if index == 0:
            self.show_composer()

    def _sender_tab(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left, ll = card()
        left.setObjectName("friendsPane")
        left.setMinimumWidth(300)
        ll.setContentsMargins(20, 24, 16, 18)
        ll.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(label("채팅", "headline"))
        self.friend_count = label("0")
        row.addWidget(self.friend_count)
        row.addStretch()
        self.reload_button = button("↻", self.load_friends, "textButton")
        self.reload_button.setToolTip("채팅 목록 새로고침")
        self.reload_button.setAccessibleName("채팅 목록 새로고침")
        self.reload_button.setFixedWidth(32)
        row.addWidget(self.reload_button)
        ll.addLayout(row)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("채팅방 검색")
        self.search.setAccessibleName("대화방 제목 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_friends)
        ll.addWidget(self.search)
        controls = QHBoxLayout()
        self.select_all = button("전체 선택", lambda: self.select_visible(True), "textButton")
        self.clear_all = button("선택 해제", self.clear_recipients, "textButton")
        controls.addWidget(self.select_all)
        controls.addWidget(self.clear_all)
        controls.addStretch()
        self.selection_count = label("0개 선택", "count")
        controls.addWidget(self.selection_count)
        ll.addLayout(controls)
        self.friend_table = FriendTable()
        self.friend_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.friend_table.itemChanged.connect(self.friend_selection_changed)
        ll.addWidget(self.friend_table, 1)
        self.empty_friends = label("채팅방 목록을 불러오는 중입니다.")
        self.empty_friends.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.empty_friends, 1)
        self.list_note = label("대화방을 클릭해 선택하세요.")
        ll.addWidget(self.list_note)
        ll.addWidget(self.connection_badge)
        right = QWidget()
        right.setMinimumWidth(470)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        canvas = QFrame()
        canvas.setObjectName("chatCanvas")
        cl = QVBoxLayout(canvas)
        cl.setContentsMargins(28, 26, 28, 0)
        cl.setSpacing(14)
        heading = QHBoxLayout()
        heading.addWidget(label("메시지", "section"))
        heading.addStretch()
        cl.addLayout(heading)
        self.recipient_summary = label("받는 대화방을 선택하세요", "chatHint")
        cl.addWidget(self.recipient_summary)
        self.draft_scroll = QScrollArea()
        self.draft_scroll.setWidgetResizable(True)
        self.draft_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.draft_scroll.setMinimumHeight(230)
        draft = QFrame()
        draft.setObjectName("draftCard")
        draft_layout = QVBoxLayout(draft)
        draft_layout.setContentsMargins(0, 20, 0, 20)
        draft_layout.setSpacing(14)
        self.photo_button = button("＋", self.choose_photos, "attach")
        self.photo_button.setAccessibleName("사진 추가")
        self.photo_button.setFixedSize(36, 36)
        self.photo_button.setToolTip("사진 추가 · JPG, PNG, WEBP, BMP · 최대 10장")
        self.message_count = label("0 / 10,000자")
        self.message = QPlainTextEdit()
        self.message.setObjectName("message")
        self.message.setMinimumHeight(160)
        self.message.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.message.setPlaceholderText("메시지 입력")
        self.message.setAccessibleName("보낼 메시지")
        self.message.textChanged.connect(self.update_selection)
        draft_layout.addWidget(self.message, 1)
        self.photo_preview = QWidget()
        self.photo_grid = QGridLayout(self.photo_preview)
        self.photo_grid.setContentsMargins(0, 0, 0, 0)
        self.photo_grid.setSpacing(12)
        self.photo_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        draft_layout.addWidget(self.photo_preview)
        self.photo_preview.hide()
        self.draft_scroll.setWidget(draft)
        cl.addWidget(self.draft_scroll, 1)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(canvas)
        rl.addWidget(self.preview_stack, 1)
        composer, compose = card()
        composer.setObjectName("sendActions")
        compose.setContentsMargins(22, 12, 22, 16)
        compose.setSpacing(10)
        self.send_settings = QWidget()
        settings = QHBoxLayout(self.send_settings)
        settings.setContentsMargins(0, 0, 0, 0)
        self.live = VisibleCheckBox("실제 전송")
        self.live.setEnabled(False)
        self.live.toggled.connect(self.update_selection)
        settings.addWidget(self.live, alignment=Qt.AlignmentFlag.AlignVCenter)
        settings.addSpacing(18)
        interval_group = QWidget()
        interval_layout = QHBoxLayout(interval_group)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.setSpacing(8)
        interval_label = label("전송 간격", "chatHint")
        interval_label.setWordWrap(False)
        interval_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        interval_label.setFixedHeight(32)
        interval_layout.addWidget(interval_label)
        self.interval = VisibleSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(2)
        self.interval.setSuffix(" 초")
        self.interval.setFixedSize(76, 32)
        self.interval.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.interval.setAccessibleName("대화방 간 전송 간격")
        interval_label.setBuddy(self.interval)
        interval_layout.addWidget(self.interval)
        interval_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        settings.addWidget(interval_group, alignment=Qt.AlignmentFlag.AlignVCenter)
        settings.addStretch()
        self.message_count.setWordWrap(False)
        self.message_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        settings.addWidget(self.message_count, alignment=Qt.AlignmentFlag.AlignVCenter)
        compose.addWidget(self.send_settings)
        self.send_hint = label("대상을 선택하고 내용을 작성하세요. 실제 전송은 직접 켤 수 있습니다.", "chatHint")
        self.send_hint.hide()
        actions = QHBoxLayout()
        self.start_button = button("대상 확인", self.start_action, "primary")
        self.start_button.setMinimumWidth(106)
        self.stop_button = button("중지", self.stop, "stop")
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        actions.addWidget(self.photo_button)
        actions.addStretch()
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        compose.addLayout(actions)
        rl.addWidget(composer)
        history = QFrame()
        history.setObjectName("history")
        hl = QVBoxLayout(history)
        hl.setContentsMargins(22, 6, 22, 8)
        hl.setSpacing(6)
        header = QHBoxLayout()
        self.history_toggle = button("진행 내역 보기", self.toggle_history, "textButton")
        self.history_toggle.setCheckable(True)
        header.addWidget(self.history_toggle)
        header.addStretch()
        self.export_button = button("CSV 저장", self.export_results, "textButton")
        self.export_button.setEnabled(False)
        self.export_button.hide()
        header.addWidget(self.export_button)
        hl.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        self.progress.hide()
        hl.addWidget(self.progress)
        history_page, history_layout = card()
        history_page.setObjectName("historyPage")
        history_layout.setContentsMargins(24, 20, 24, 16)
        history_heading = QHBoxLayout()
        history_heading.addWidget(label("진행 내역", "section"))
        history_heading.addStretch()
        self.back_to_composer = button("← 메시지 작성", self.show_composer, "textButton")
        self.back_to_composer.setAccessibleName("메시지 작성으로 돌아가기")
        self.back_to_composer.setMinimumHeight(38)
        history_heading.addWidget(self.back_to_composer)
        history_layout.addLayout(history_heading)
        history_layout.addWidget(label("대화방별 처리 결과를 확인하세요. CSV로 저장할 수 있습니다."))
        self.log = QTextEdit()
        self.log.setObjectName("resultLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(100)
        self.log.setPlaceholderText("대상 확인 및 발송 결과가 여기에 표시됩니다.")
        history_layout.addWidget(self.log, 1)
        self.preview_stack.addWidget(history_page)
        rl.addWidget(history)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 660])
        layout.addWidget(split)
        self.tabs.addTab(page, "메시지 보내기")

    def toggle_history(self, checked: bool) -> None:
        self.history_toggle.blockSignals(True)
        self.history_toggle.setChecked(checked)
        self.history_toggle.blockSignals(False)
        self.preview_stack.setCurrentIndex(1 if checked else 0)
        self.send_settings.setVisible(not checked)
        self.photo_button.setVisible(not checked)
        self.history_toggle.setText("메시지 작성으로 돌아가기" if checked else "진행 내역 보기")
        self.update_selection()

    def start_action(self) -> None:
        if self.preview_stack.currentIndex() == 1:
            self.show_composer()
        else:
            self.preview()

    def show_composer(self) -> None:
        self.toggle_history(False)
        if self.task is None:
            self.message.setFocus(Qt.FocusReason.OtherFocusReason)

    def clear_recipients(self) -> None:
        self.select_visible(False, all_rows=True)

    def friend_selection_changed(self, *_args) -> None:
        self.update_selection()

    def choose_photos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "보낼 사진 선택", "", PHOTO_FILTER)
        if paths:
            self.add_photo_paths([Path(path) for path in paths])

    def add_photo_paths(self, paths: list[Path]) -> None:
        if self.task is not None or not paths:
            return
        if len(self.photos) + len(paths) > MAX_PHOTOS:
            self.show_error("사진은 한 번에 10장까지 선택할 수 있습니다.")
            return
        existing = self.photos

        def work(stop: Event, report) -> tuple[Photo, ...]:
            added = []
            for path in paths:
                checkpoint(stop)
                added.append(load_photo(path))
            photos = existing + tuple(added)
            validate_photos(photos)
            return photos

        self.status.setText("사진을 불러오고 있습니다…")
        self.launch(work, self.on_photos)

    def on_photos(self, photos: tuple[Photo, ...]) -> None:
        self.photos = photos
        self.refresh_photos()
        self.history_toggle.setChecked(False)
        self.toggle_history(False)
        self.status.setText(f"사진 {len(photos)}장 준비됨 · 글 다음에 사진을 선택한 순서대로 한 장씩 전송합니다.")

    def remove_photo(self, index: int) -> None:
        if self.task is not None:
            return
        self.photos = self.photos[:index] + self.photos[index + 1:]
        self.refresh_photos()

    def refresh_photos(self) -> None:
        while self.photo_grid.count():
            item = self.photo_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, photo in enumerate(self.photos):
            tile = QWidget()
            tile.setFixedWidth(144)
            layout = QVBoxLayout(tile)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            thumbnail = QPushButton()
            thumbnail.setAccessibleName(f"사진 {index + 1}: {photo.name} 크게 보기")
            thumbnail.setToolTip(photo.name)
            thumbnail.setFixedSize(144, 80)
            pixmap = QPixmap()
            pixmap.loadFromData(photo.thumbnail or photo.content, "PNG")
            thumbnail.setIcon(QIcon(pixmap))
            thumbnail.setIconSize(QSize(132, 70))
            thumbnail.clicked.connect(lambda checked=False, photo=photo: self.show_photo(photo))
            controls = QHBoxLayout()
            caption = label(f"{index + 1}. {photo.name[:13]}" + ("…" if len(photo.name) > 13 else ""), "chatHint")
            caption.setToolTip(photo.name)
            controls.addWidget(caption, 1)
            remove = button("×", lambda checked=False, index=index: self.remove_photo(index), "textButton")
            remove.setAccessibleName(f"사진 {index + 1} 삭제")
            remove.setToolTip("이 사진 삭제")
            remove.setFixedSize(24, 26)
            controls.addWidget(remove)
            layout.addLayout(controls)
            layout.addWidget(thumbnail)
            self.photo_grid.addWidget(tile, index // 2, index % 2)
        self.photo_preview.setVisible(bool(self.photos))
        self.message.setMinimumHeight(88 if self.photos else 160)
        self.photo_button.setToolTip(f"사진 추가 · {len(self.photos)}/{MAX_PHOTOS}장" if self.photos else "사진 추가")
        self.update_selection()

    def show_photo(self, photo: Photo) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(photo.name)
        layout = QVBoxLayout(dialog)
        picture = QLabel()
        pixmap = QPixmap()
        pixmap.loadFromData(photo.content, "PNG")
        picture.setPixmap(pixmap.scaled(720, 500, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(picture)
        layout.addWidget(label(f"{photo.width:,} × {photo.height:,} · {len(photo.content) / 1024 / 1024:.1f} MB"))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def _setup_tab(self):
        page = QWidget()
        page.setObjectName("connectionPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 12, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("내 카카오톡 연결하기", "section"))
        layout.addWidget(label("카카오톡 메인 창의 채팅 탭을 열어 주세요.\n손쉬운 사용에서 이 앱을 허용한 뒤, 보내기 화면에서 채팅방 목록을 새로고침하세요."))
        row = QHBoxLayout()
        self.connection_button = button("연결 상태 확인", self.check_connection)
        row.addWidget(self.connection_button)
        if sys.platform == "darwin":
            row.addWidget(button("손쉬운 사용 설정 열기", lambda: QDesktopServices.openUrl(
                QUrl("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"))))
        row.addStretch()
        layout.addLayout(row)
        self.connection_label = label("연결 상태 확인을 눌러 권한과 카카오톡 실행 여부를 확인하세요.")
        self.connection_label.setStyleSheet("background: #252525; border: 1px solid #363636; border-radius: 8px; padding: 16px; color: #bbbbbb;")
        layout.addWidget(self.connection_label)
        self.advanced_toggle = button("고급 연결 설정 열기", self.toggle_advanced, "textButton")
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.advanced_panel = QWidget()
        advanced = QVBoxLayout(self.advanced_panel)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.addWidget(label("연결이 되지 않거나 화면 구조가 바뀌었을 때 사용하는 설정입니다.\n화면 읽기 결과에는 대화방 제목과 대화 내용이 포함될 수 있습니다."))
        tools = QHBoxLayout()
        self.inspect_button = button("카카오톡 화면 읽기", self.inspect)
        self.save_diag_button = button("진단 JSON 저장", self.export_snapshot)
        tools.addWidget(self.inspect_button)
        tools.addWidget(self.save_diag_button)
        tools.addStretch()
        advanced.addLayout(tools)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["이름", "Role", "Identifier"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 120)
        split.addWidget(self.tree)
        pane = QWidget()
        pl = QVBoxLayout(pane)
        self.field = VisibleComboBox()
        for key, title in PROFILE_FIELDS.items():
            if key not in {"chat_window", "editor", "send_button"}:
                continue
            self.field.addItem(title, key)
        pl.addWidget(self.field)
        self.assign_button = button("선택한 요소를 이 용도로 지정", self.assign)
        pl.addWidget(self.assign_button)
        pl.addWidget(label("채팅방 목록 연결에는 대화 창·입력창·전송 버튼 조건만 사용합니다. 친구 목록과 프로필 설정은 사용하지 않습니다."))
        self.profile_text = QPlainTextEdit()
        self.profile_text.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 11))
        self.profile_text.setPlainText(json.dumps(self.profile, ensure_ascii=False, indent=2))
        pl.addWidget(self.profile_text, 1)
        row = QHBoxLayout()
        self.load_profile_button = button("프로필 열기", self.load_profile)
        self.save_profile_button = button("설정 적용 · 저장", self.save_profile)
        row.addWidget(self.load_profile_button)
        row.addWidget(self.save_profile_button)
        pl.addLayout(row)
        split.addWidget(pane)
        split.setSizes([580, 460])
        advanced.addWidget(split, 1)
        layout.addWidget(self.advanced_panel, 1)
        self.advanced_panel.hide()
        self.setup_spacer = QWidget()
        layout.addWidget(self.setup_spacer, 1)
        self.tabs.addTab(page, "연결 설정 / 진단")

    def toggle_advanced(self, checked: bool) -> None:
        self.advanced_panel.setVisible(checked)
        self.setup_spacer.setVisible(not checked)
        self.advanced_toggle.setText("고급 연결 설정 닫기" if checked else "고급 연결 설정 열기")

    def set_busy(self, busy):
        for widget in [self.reload_button, self.search, self.friend_table,
                       self.select_all, self.clear_all, self.message, self.interval, self.photo_button, self.photo_preview,
                       self.inspect_button, self.connection_button, self.assign_button, self.load_profile_button,
                       self.save_profile_button, self.profile_text, self.export_button]:
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.stop_button.setVisible(busy)
        self.export_button.setEnabled(not busy and bool(self.results))
        self.export_button.setVisible(bool(self.results))
        self.live.setEnabled(not busy and bool(self.friends and self.friends.complete))
        self.update_selection()

    def launch(self, fn, callback, error_callback=None):
        if self.task is not None:
            return
        task = Task(fn, self)
        self.task = task
        task.done.connect(callback)
        task.failed.connect(error_callback or self.show_error)
        task.progress.connect(self.on_result)
        task.finished.connect(self.task_finished)
        self.set_busy(True)
        task.start()

    def task_finished(self):
        task, self.task = self.task, None
        if task:
            task.deleteLater()
        self.set_busy(False)
        if self._close_pending and self.watch_task is None:
            self.close()

    def poll_open_chats(self) -> None:
        if (self.task is not None or self.watch_task is not None
                or self._close_pending or QApplication.activeModalWidget() is not None):
            return
        profile = json.loads(json.dumps(self.profile))
        catalog = self.friends.catalog if self.friends else None

        def work(stop: Event, report) -> FriendList:
            backend = ConversationBackend(native_driver(), profile, catalog=catalog)
            try:
                return backend.list_friends(stop)
            finally:
                backend.close()

        task = Task(work, self)
        self.watch_task = task
        task.done.connect(self.on_auto_chats)
        task.failed.connect(self.on_auto_chat_error)
        task.finished.connect(self.watch_finished)
        task.start()

    def watch_finished(self) -> None:
        task, self.watch_task = self.watch_task, None
        if task:
            task.deleteLater()
        if self._close_pending and self.task is None:
            self.close()

    def on_auto_chats(self, result: FriendList) -> None:
        if (self.task is not None or self._close_pending
                or QApplication.activeModalWidget() is not None):
            return
        if result == self.friends:
            return
        previous = {friend.key: friend for friend in self.selected()}
        # Keep the originally selected native handle, even if an OS hash is reused.
        # The send backend will reject it if it no longer refers to the same window.
        result = replace(result, friends=tuple(
            previous[friend.key] if friend.selectable and friend.key in previous
            and previous[friend.key].name == friend.name else friend for friend in result.friends))
        self.on_friends(result)
        self.friend_table.blockSignals(True)
        for row, friend in enumerate(result.friends):
            if friend.selectable and friend.key in previous:
                self.friend_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        self.friend_table.blockSignals(False)
        if len(self.selected()) != len(previous):
            self.live.setChecked(False)
            self.status.setText("선택한 채팅 행이 사라지거나 변경돼 선택을 해제했습니다.")
        else:
            self.status.setText("채팅방 목록이 자동으로 반영됐습니다.")
        self.live.setEnabled(bool(result.complete))
        self.update_selection()

    def on_auto_chat_error(self, message: str) -> None:
        if (self.task is not None or self._close_pending
                or QApplication.activeModalWidget() is not None):
            return
        self.on_connection_error(message)

    def on_connection_error(self, message: str) -> None:
        if self._close_pending:
            return
        self.set_connection_badge("연결 필요", "waiting")
        self.friends = None
        self.friend_table.setRowCount(0)
        self.friend_table.hide()
        self.friend_count.setText("0")
        self.live.setChecked(False)
        self.live.setEnabled(False)
        self.empty_friends.setText(message)
        self.empty_friends.show()
        self.list_note.setText("왼쪽 아래 설정에서 연결을 확인하세요.")
        self.list_note.show()
        self.status.setText("채팅방 목록 연결을 기다리고 있습니다.")
        self.update_selection()

    def show_error(self, message):
        if self._close_pending:
            return
        self.status.setText(message)
        if self.friends is None:
            self.friend_count.setText("0")
            self.empty_friends.setText("목록을 불러오지 못했어요.\n연결 설정을 확인하고 다시 시도해 주세요.")
            self.friend_table.hide()
            self.empty_friends.show()
        QMessageBox.warning(self, "작업 확인", message)

    def factory(self):
        profile = json.loads(json.dumps(self.profile))
        pid = self.friends.session_pid if self.friends else None
        catalog = self.friends.catalog if self.friends else None

        def make():
            return ConversationBackend(native_driver(), profile, pid, catalog)
        return make

    def load_friends(self):
        if self.task is not None or self._close_pending:
            return
        # A new read may bind to a restarted client; a send may not.
        self.friends = None
        self.friend_table.setRowCount(0)
        self.live.setChecked(False)
        make = self.factory()

        def work(stop, report):
            backend = make()
            try:
                return backend.list_friends(stop)
            finally:
                backend.close()
        self.status.setText("채팅방 목록을 조회하고 있습니다…")
        self.friend_count.setText("조회 중")
        self.empty_friends.setText("카카오톡의 메인 채팅 목록을 확인하고 있어요…")
        self.friend_table.hide()
        self.empty_friends.show()
        self.launch(work, self.on_friends, self.on_connection_error)

    def set_connection_badge(self, text: str, state: str) -> None:
        self.connection_badge.setText(text)
        self.connection_badge.setProperty("state", state)
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)

    def on_friends(self, result: FriendList):
        self.set_connection_badge("카카오톡 연결됨", "connected")
        self.friends = result
        self.friend_table.blockSignals(True)
        self.friend_table.setRowCount(len(result.friends))
        for row, friend in enumerate(result.friends):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if friend.selectable else Qt.ItemFlag.NoItemFlags)
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            checkbox.setData(Qt.ItemDataRole.AccessibleTextRole, friend.name + " 선택")
            checkbox.setToolTip("클릭 또는 스페이스 키로 선택" if friend.selectable else friend.note)
            self.friend_table.setItem(row, 0, checkbox)
            name_item = QTableWidgetItem(friend.name)
            name_item.setToolTip(friend.name + ("\n" + friend.note if friend.note else ""))
            self.friend_table.setItem(row, 1, name_item)
            self.friend_table.setItem(row, 2, QTableWidgetItem(friend.note))
        self.friend_table.blockSignals(False)
        blocked = sum(not friend.selectable for friend in result.friends)
        self.friend_count.setText(str(len(result.friends)))
        self.list_note.setText(f"{blocked}개 대화창은 제목 중복 또는 목록 행 열기 미지원으로 선택할 수 없어요."
                               if blocked else "대화방 행을 클릭하거나 스페이스 키로 선택하세요.")
        self.list_note.setToolTip(result.note)
        self.list_note.setVisible(blocked > 0)
        self.status.setText("목록을 불러왔습니다. 메시지를 보낼 대화방을 선택해 주세요.")
        self.filter_friends()

    def filter_friends(self):
        term = self.search.text().casefold()
        for row in range(self.friend_table.rowCount()):
            self.friend_table.setRowHidden(row, term not in self.friend_table.item(row, 1).text().casefold())
        visible = sum(not self.friend_table.isRowHidden(row) for row in range(self.friend_table.rowCount()))
        self.friend_table.setVisible(visible > 0)
        self.empty_friends.setVisible(visible == 0)
        self.empty_friends.setText("검색 결과가 없어요. 다른 이름으로 검색해 보세요." if term else "채팅방 목록이 비어 있습니다. 카카오톡 메인 창의 채팅 탭을 확인하세요.")
        self.select_all.setText("검색 결과 선택" if term else "전체 선택")
        self.update_selection()

    def select_visible(self, selected, all_rows=False):
        if not self.friends:
            return
        self.friend_table.blockSignals(True)
        for row, friend in enumerate(self.friends.friends):
            if friend.selectable and (all_rows or not self.friend_table.isRowHidden(row)):
                self.friend_table.item(row, 0).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
        self.friend_table.blockSignals(False)
        self.friend_table.viewport().update()
        self.update_selection()

    def selected(self):
        if not self.friends:
            return ()
        return tuple(friend for i, friend in enumerate(self.friends.friends)
                     if friend.selectable and self.friend_table.item(i, 0).checkState() == Qt.CheckState.Checked)

    def update_selection(self, *_args) -> None:
        friends = self.selected()
        count = len(friends)
        message = self.message.toPlainText()
        self.selection_count.setText(f"{count}개 선택")
        self.message_count.setText(f"{len(message):,} / 10,000자")
        self.message_count.setStyleSheet("color: #b13f3f;" if len(message) > 10000 else "")
        names = ", ".join(friend.name for friend in friends[:3])
        if len(names) > 38:
            names = names[:38] + "…"
        if count > 3:
            names += f" 외 {count - 3}개"
        self.recipient_summary.setText(f"대화방 {count}개 · {names}" if count else "받는 대화방을 선택하세요")
        self.recipient_summary.setToolTip("\n".join(friend.name for friend in friends))
        if self.live.isChecked():
            hint = "다음 화면에서 대상과 내용을 확인한 뒤 전송합니다."
        else:
            hint = "현재는 대상 확인만 합니다. 메시지를 보내려면 ‘실제 전송’을 켜세요."
        if self.photos:
            order = ("글 → " if message.strip() else "") + f"사진 {len(self.photos)}장"
            if self.live.isChecked():
                hint = f"미리보기 확인 후 {order}을 한 건씩 전송합니다."
            else:
                hint = f"현재는 대상 확인만 합니다. 실제 전송을 켜면 {order} 순서로 보냅니다."
        self.send_hint.setText(hint)
        self.start_button.setToolTip(hint)
        self.live.setToolTip(hint)
        self.start_button.setText("전송" if self.live.isChecked() else "대상 확인")
        allowed = bool(self.friends and self.friends.complete)
        self.start_button.setEnabled(self.task is None and count > 0 and (bool(message.strip()) or bool(self.photos))
                                     and len(message) <= 10000 and allowed)
        if self.preview_stack.currentIndex() == 1:
            self.start_button.setText("메시지 작성으로 돌아가기")
            self.start_button.setEnabled(True)
        self.clear_all.setEnabled(self.task is None and count > 0)
        self.select_all.setEnabled(self.task is None and bool(self.friends) and any(
            friend.selectable and not self.friend_table.isRowHidden(row)
            for row, friend in enumerate(self.friends.friends if self.friends else ())))

    def preview(self):
        if not self.friends:
            return
        plan = Plan(self.selected(), self.message.toPlainText(), self.friends.scope,
                    self.live.isChecked(), self.interval.value(), self.photos)
        try:
            plan.validate()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("발송 미리보기" if plan.live else "대상 확인 미리보기")
        dialog.resize(570, 600 if plan.photos else 530)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(f"대화방 {len(plan.recipients)}개에 각각 전달" if plan.live else f"대화방 {len(plan.recipients)}개 확인", "section"))
        recipients = QPlainTextEdit("\n".join(f.name for f in plan.recipients))
        recipients.setReadOnly(True)
        recipients.setMaximumHeight(140)
        layout.addWidget(recipients)
        if plan.message.strip():
            message = QPlainTextEdit(plan.message)
            message.setReadOnly(True)
            layout.addWidget(message, 1)
        if plan.photos:
            layout.addWidget(label(f"사진 {len(plan.photos)}장 · " + ("글 다음에 " if plan.message.strip() else "") + "아래 순서로 한 장씩 전송", "section"))
            photo_scroll = QScrollArea()
            photo_scroll.setWidgetResizable(True)
            photo_scroll.setMinimumHeight(160)
            content = QWidget()
            photo_layout = QGridLayout(content)
            for index, photo in enumerate(plan.photos):
                tile = QPushButton(f"{index + 1}. {photo.name[:16]}")
                pixmap = QPixmap()
                pixmap.loadFromData(photo.thumbnail or photo.content, "PNG")
                tile.setIcon(QIcon(pixmap))
                tile.setIconSize(QSize(76, 64))
                tile.setToolTip(photo.name)
                tile.clicked.connect(lambda checked=False, photo=photo: self.show_photo(photo))
                photo_layout.addWidget(tile, index // 2, index % 2)
            photo_scroll.setWidget(content)
            layout.addWidget(photo_scroll, 1)
        layout.addWidget(label("글·사진 전송이 모두 완료된 대화창은 자동으로 닫습니다. 작업 중에는 카카오톡을 조작하지 마세요."
                               if plan.live else "메시지 입력·전송 없이 대화 상대와 입력창만 확인합니다."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        go = buttons.addButton(f"대화방 {len(plan.recipients)}개에 전송" if plan.live else "대상 확인 시작", QDialogButtonBox.ButtonRole.AcceptRole)
        go.setObjectName("primary")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.run_plan(plan)

    def run_plan(self, plan):
        make = self.factory()
        path = data_dir() / "attempts.sqlite3"
        self.results.clear()
        self.log.clear()
        self.history_toggle.setChecked(True)
        self.toggle_history(True)
        self.progress.setRange(0, len(plan.recipients))
        self.progress.setValue(0)
        self.progress.show()

        def work(stop, report):
            backend = make()
            try:
                journal = Journal(path)
                try:
                    return execute(plan, backend, journal, stop, report)
                finally:
                    journal.close()
            finally:
                backend.close()
        self.status.setText("실제 전송 진행 중…" if plan.live else "대상 확인 중…")
        self.launch(work, lambda result: self.status.setText(f"작업 종료 · 처리 {len(result)} / {len(plan.recipients)}개 · 진행 내역을 확인해 주세요."))

    def on_result(self, result):
        self.results.append(result)
        self.export_button.show()
        self.progress.setValue(len(self.results))
        background, foreground = RESULT_COLORS[result.state]
        self.log.append(
            f'<table width="100%" cellspacing="0" cellpadding="12" bgcolor="{background}"><tr><td>'
            f'<b>{escape(result.friend.name)}</b> &nbsp; '
            f'<span style="color:{foreground}"><b>{STATES[result.state]}</b></span><br>'
            f'<span style="color:#a0a0a0">{escape(result.detail).replace(chr(10), "<br>")}</span>'
            '</td></tr></table><br>')

    def stop(self):
        if self.task:
            self.task.stop.set()
            self.status.setText("중지 요청됨 · 진행 중인 OS 호출이 끝나면 중지합니다.")

    def inspect(self):
        def work(stop, report):
            driver = native_driver()
            try:
                return driver.snapshot(stop)
            finally:
                driver.close()
        self.status.setText("카카오톡의 접근성 화면 요소를 읽고 있습니다…")
        self.launch(work, self.on_snapshot)

    def check_connection(self) -> None:
        if sys.platform != "darwin":
            self.connection_label.setText("Windows에서는 화면·접근성 진단만 지원합니다.\n\n카카오톡 목록 조회와 글·사진 전송은 현재 macOS에서만 지원합니다.")
            self.set_connection_badge("전송 미지원", "waiting")
            return
        from .adapters.macos import connection_status
        state = connection_status()
        state["connection_mode"] = "conversation-list"
        lines = [
            "손쉬운 사용 권한: " + ("허용됨" if state["accessibility_trusted"] else "허용 필요"),
            f"카카오톡 실행: {state['kakao_process_count']}개",
            "연결 방식: 채팅 목록 조회 → 선택한 방 열기 → 대상 확인 후 전송",
        ]
        self.connection_label.setText("\n\n".join(lines))
        if not state["accessibility_trusted"]:
            self.set_connection_badge("권한 필요", "waiting")
        elif state["kakao_process_count"] != 1:
            self.set_connection_badge("카카오톡 실행 필요", "waiting")
        self.connection_label.setToolTip(f"현재 앱: {state['app_path']}")
        try:
            (data_dir() / "connection-status.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            self.connection_label.setText("\n".join(lines) + "\n연결 상태 파일을 저장하지 못했습니다.")

    def on_snapshot(self, snapshot):
        self.snapshot_data = snapshot
        self.tree.clear()
        items = {}
        for node in snapshot["nodes"]:
            item = QTreeWidgetItem([node["name"] or "(이름 없음)", node["role"], node["identifier"]])
            item.setData(0, Qt.ItemDataRole.UserRole, node)
            parent_path = node["path"].rsplit("/", 1)[0] if "/" in node["path"] else None
            if parent_path in items:
                items[parent_path].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            items[node["path"]] = item
        self.tree.expandToDepth(1)
        self.status.setText(snapshot.get("error") or f"화면 요소 {len(snapshot['nodes'])}개를 읽었습니다.")

    def assign(self):
        item = self.tree.currentItem()
        if item is None:
            self.show_error("먼저 왼쪽 트리에서 화면 요소를 선택해 주세요.")
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        key = self.field.currentData()
        try:
            profile = json.loads(self.profile_text.toPlainText())
            selector = {k: node[k] for k in ["role", "name", "identifier"] if node[k]}
            if key == "chat_window":
                selector.pop("name", None)
            profile["selectors"][key] = selector
            self.profile_text.setPlainText(json.dumps(profile, ensure_ascii=False, indent=2))
        except (ValueError, KeyError, TypeError) as exc:
            self.show_error(f"프로필 JSON을 확인해 주세요: {exc}")

    def save_profile(self):
        try:
            profile = json.loads(self.profile_text.toPlainText())
            if profile.get("version") != 1 or not isinstance(profile.get("selectors"), dict):
                raise ValueError("version=1과 selectors 객체가 필요합니다.")
            if profile.get("platform") != sys.platform:
                raise ValueError("현재 운영체제와 프로필의 platform이 다릅니다.")
            temporary = self.profile_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.profile_path)
            self.profile = profile
            self.friends = None
            self.friend_table.setRowCount(0)
            self.live.setChecked(False)
            self.live.setEnabled(False)
            self.update_selection()
            self.status.setText("연결 설정을 저장했습니다. 채팅방 목록을 다시 불러와 주세요.")
        except (ValueError, OSError, AttributeError) as exc:
            self.show_error(str(exc))

    def load_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "프로필 열기", "", "JSON (*.json)")
        if path:
            try:
                profile = json.loads(Path(path).read_text(encoding="utf-8"))
                self.profile_text.setPlainText(json.dumps(profile, ensure_ascii=False, indent=2))
                self.status.setText("프로필을 열었습니다. ‘설정 적용 · 저장’을 누르면 적용됩니다.")
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))

    def export_snapshot(self):
        if self.snapshot_data is None:
            self.show_error("먼저 카카오톡 화면을 읽어 주세요.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "진단 저장", "diagnostic-private.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(self.snapshot_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as exc:
                self.show_error(str(exc))

    def export_results(self):
        path, _ = QFileDialog.getSaveFileName(self, "진행 내역 저장", "send-results.csv", "CSV (*.csv)")
        if not path:
            return
        def safe(value):
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["이름", "상태", "상세"])
                for result in self.results:
                    writer.writerow([safe(result.friend.name), STATES[result.state], safe(result.detail)])
        except OSError as exc:
            self.show_error(str(exc))

    def closeEvent(self, event):
        self._close_pending = True
        self.chat_timer.stop()
        if self.watch_task is not None:
            self.watch_task.stop.set()
        if self.task is not None or self.watch_task is not None:
            self.stop()
            event.ignore()
            return
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("KakaoFriendSender")
    apply_theme(app)
    window = Window()
    window.show()
    return app.exec()
