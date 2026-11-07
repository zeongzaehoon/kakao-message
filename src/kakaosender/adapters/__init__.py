from __future__ import annotations

import sys


def native_driver():
    if sys.platform == "win32":
        from .windows import WindowsDriver
        return WindowsDriver()
    if sys.platform == "darwin":
        from .macos import MacDriver
        return MacDriver()
    from ..models import IntegrationError
    raise IntegrationError("실제 카카오톡 연결은 Windows 또는 macOS에서 실행해 주세요.")
