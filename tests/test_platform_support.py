import json
import sys

from kakaosender.__main__ import main


def test_windows_connection_check_reports_unsupported_without_macos_imports(tmp_path, monkeypatch):
    report = tmp_path / "connection.json"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["kakaosender", "--connection-check", str(report)])
    monkeypatch.setitem(sys.modules, "ApplicationServices", None)
    assert main() == 1
    state = json.loads(report.read_text(encoding="utf-8"))
    assert state["platform"] == "win32"
    assert state["sending_supported"] is False
    assert "macOS" in state["error"]
