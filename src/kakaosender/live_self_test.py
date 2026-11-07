"""Explicitly invoked, real text/photo test restricted to the current account's self chat."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event


def run_self_prepare_check(report: Path, target_path: Path) -> int:
    """Validate the explicitly confirmed open self-chat without typing/sending."""
    import time
    from .adapters import native_driver
    from .open_chat_checks import confirmed_self_target, self_test_backend
    backend = None
    started = time.monotonic()
    try:
        backend = self_test_backend(native_driver(), target_path)
        own, scope = confirmed_self_target(backend, target_path)
        backend.prepare(own, scope, Event())
        payload = {"ok": True, "prepared": True, "input_empty": True}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    finally:
        if backend is not None:
            backend.close()
    payload.update(self_only=True, sent=0, elapsed_seconds=round(time.monotonic() - started, 2))
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1


def run_live_self_test(report: Path, target_path: Path) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QColor, QPainter, QFont
    from .adapters import native_driver
    from .open_chat_checks import confirmed_self_target, self_test_backend
    from .attachments import load_photo
    from .engine import execute
    from .models import Plan
    from .storage import Journal, data_dir

    app = QApplication.instance() or QApplication([])
    backend = journal = None
    try:
        backend = self_test_backend(native_driver(), target_path)
        own, scope = confirmed_self_target(backend, target_path)
        with TemporaryDirectory(prefix="kakaosender-self-photo-") as temporary:
            picture = QImage(640, 400, QImage.Format.Format_RGB32)
            picture.fill(QColor("#fee500"))
            painter = QPainter(picture)
            painter.setPen(QColor("#302b22"))
            painter.setFont(QFont("Apple SD Gothic Neo", 26))
            painter.drawText(picture.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Kakao Friend Sender\n사진 전송 테스트")
            painter.end()
            photo_path = Path(temporary) / "self-test.png"
            if not picture.save(str(photo_path)):
                raise ValueError("테스트 이미지를 만들지 못했습니다.")
            plan = Plan((own,), "Kakao Friend Sender 수정 확인: 글·사진 전송과 전송 후 대화창 닫기를 테스트합니다.",
                        scope, True, 0, (load_photo(photo_path),))
            journal = Journal(data_dir() / "attempts.sqlite3")
            results = execute(plan, backend, journal, Event(), lambda result: None)
            identities = [journal.identity(plan.scope, own.key, plan.message)]
            identities.extend(journal.identity(plan.scope, own.key, plan.message, item.fingerprint) for item in plan.photos)
            states = [journal.db.execute("SELECT state FROM attempts WHERE identity=?", (identity,)).fetchone()
                      for identity in identities]
            # A skipped pending/uncertain attempt is not a successful test.
            closed = own.key in backend.closed_recipients
            payload = {"ok": bool(results) and all(state == ("submitted",) for state in states)
                       and all(result.state in {"submitted", "duplicate"} for result in results) and closed,
                       "chat_closed": closed,
                       "self_only": True, "recipients": 1,
                       "results": [{"state": result.state, "detail": result.detail} for result in results]}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "self_only": True}
    finally:
        if journal is not None:
            journal.close()
        if backend is not None:
            backend.close()
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1
