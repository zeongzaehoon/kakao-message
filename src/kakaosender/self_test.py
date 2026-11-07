"""Exercise the frozen runtime without touching KakaoTalk or user history."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def run_self_test(report: Path) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QImage, QColor
    from . import ui
    from .models import Plan
    from .test_support import FixtureBackend

    if sys.platform == "darwin":
        import ApplicationServices as AX
        from AppKit import NSWorkspace
        from CoreFoundation import CFHash
        assert callable(AX.AXUIElementCreateApplication)
        assert callable(AX.AXIsProcessTrusted)
        assert callable(CFHash)
        assert NSWorkspace is not None
        import Quartz
        assert callable(Quartz.CGEventPostToPid)
    elif sys.platform == "win32":
        import pywinauto
        import psutil
        import win32api
        assert callable(pywinauto.Desktop)
        assert callable(psutil.process_iter)
        assert callable(win32api.GetCurrentProcessId)

    app = QApplication.instance() or QApplication([])
    ui.apply_theme(app)

    def settle(window: ui.Window) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            app.processEvents()
            if window.task is None and window.friends is not None:
                return
            time.sleep(0.01)
        assert False, "Fixture worker timed out"

    original_data_dir = ui.data_dir
    with TemporaryDirectory(prefix="kakaosender-self-test-") as temporary:
        ui.data_dir = lambda: Path(temporary)
        window = None
        try:
            window = ui.Window(auto_connect=False)
            window.factory = lambda: FixtureBackend
            window.load_friends()
            window.show()
            settle(window)
            count = window.friend_table.rowCount()
            assert count == 11
            assert not window.live.isChecked()
            assert not hasattr(window, "mode")
            window.search.setText("김")
            target = window.friend_table.visualItemRect(window.friend_table.item(0, 1))
            QTest.mouseClick(window.friend_table.viewport(), Qt.MouseButton.LeftButton, pos=target.center())
            assert [friend.name for friend in window.selected()] == ["김민준"]
            message = "패키징 자체 검사 👋\n두 번째 줄"
            window.message.setPlainText(message)
            test_image = QImage(120, 80, QImage.Format.Format_RGB32)
            test_image.fill(QColor("#fee500"))
            formats = []
            for extension in ("png", "jpg", "webp", "bmp"):
                photo_path = Path(temporary) / ("self-test." + extension)
                assert test_image.save(str(photo_path))
                from .attachments import load_photo
                assert load_photo(photo_path).width == 120
                formats.append(extension)
            window.add_photo_paths([Path(temporary) / "self-test.png"])
            settle(window)
            assert len(window.photos) == 1
            if sys.platform == "darwin":
                from AppKit import NSImage
                from Foundation import NSData
                data = window.photos[0].content
                assert NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data))) is not None
            window.run_plan(Plan(window.selected(), message, "demo", False, 0, window.photos))
            settle(window)
            assert [result.state for result in window.results] == ["checked"]
            assert window.message.isEnabled()
            assert not window.grab().isNull()
            report.write_text(json.dumps({
                "ok": True,
                "frozen": bool(getattr(sys, "frozen", False)),
                "fixture_recipients": count,
                "demo_ui_removed": True,
                "selected": 1,
                "results": [result.state for result in window.results],
                "native_imports": sys.platform in {"darwin", "win32"},
                "rendered": True,
                "row_click_selected": True,
                "photos": len(window.photos),
                "photo_formats": formats,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if window is not None:
                if window.task is not None:
                    window.stop()
                    window.task.wait()
                    app.processEvents()
                window.close()
            ui.data_dir = original_data_dir
    return 0
