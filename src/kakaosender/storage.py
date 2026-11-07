from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from .models import digest


def data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    path = root / "KakaoFriendSender"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Journal:
    """A durable reservation is written BEFORE any send side effect.

    No recipient names or message bodies are stored. A pending row left by a
    crash is blocked as well as a submitted/uncertain row. This favors no
    duplicates over automatic retries; hashes are not encryption.
    """

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
            identity TEXT PRIMARY KEY, state TEXT NOT NULL,
            updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        self.db.commit()

    @staticmethod
    def identity(scope: str, recipient: str, message: str, photo_hash: str | None = None) -> str:
        import json
        payload = [scope, recipient, message] if photo_hash is None else [scope, recipient, "photo-v1", photo_hash]
        return digest(json.dumps(payload, ensure_ascii=False))

    def reserve(self, scope: str, recipient: str, message: str, photo_hash: str | None = None) -> bool:
        key = self.identity(scope, recipient, message, photo_hash)
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO attempts(identity,state) VALUES (?, 'pending')", (key,)
            )
        return cur.rowcount == 1

    def finish(self, scope: str, recipient: str, message: str, state: str, photo_hash: str | None = None) -> None:
        with self.db:
            self.db.execute("UPDATE attempts SET state=?, updated=CURRENT_TIMESTAMP WHERE identity=?",
                            (state, self.identity(scope, recipient, message, photo_hash)))

    def release(self, scope: str, recipient: str, message: str, photo_hash: str | None = None) -> None:
        with self.db:
            self.db.execute("DELETE FROM attempts WHERE identity=? AND state='pending'",
                            (self.identity(scope, recipient, message, photo_hash),))

    def state(self, scope: str, recipient: str, message: str, photo_hash: str | None = None) -> str | None:
        row = self.db.execute("SELECT state FROM attempts WHERE identity=?",
                              (self.identity(scope, recipient, message, photo_hash),)).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.db.close()
