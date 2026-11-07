"""Build and smoke-test a standalone Windows x64 executable on Windows."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tomllib


def main() -> int:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        print("Run scripts/build_windows.bat on Windows x64 with CPython 3.12 x64.", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    build = root / "build" / "windows"
    release = root / "dist" / "releases" / version
    release.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
               "--onefile", "--name", "KakaoFriendSender", "--paths", str(root / "src"),
               "--distpath", str(build / "dist"), "--workpath", str(build / "work"),
               "--specpath", str(build), "--collect-all", "pywinauto", "--collect-all", "comtypes",
               "--hidden-import", "pythoncom", "--hidden-import", "pywintypes",
               str(root / "scripts" / "launcher.py")]
    subprocess.run(command, cwd=root, check=True)
    executable = build / "dist" / "KakaoFriendSender.exe"
    content = executable.read_bytes()
    pe_offset = struct.unpack_from("<I", content, 0x3C)[0]
    if content[:2] != b"MZ" or content[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise RuntimeError("Build output is not a Windows PE executable.")
    if struct.unpack_from("<H", content, pe_offset + 4)[0] != 0x8664:
        raise RuntimeError("Build output is not x64.")
    report = build / "self-test.json"
    report.unlink(missing_ok=True)
    subprocess.run([str(executable), "--self-test", str(report)], cwd=root, check=True, timeout=180)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not all(result.get(key) for key in ("ok", "frozen", "native_imports", "demo_ui_removed", "rendered", "row_click_selected")):
        raise RuntimeError("Frozen Windows self-test failed.")
    target = release / f"Kakao-Friend-Sender-{version}-windows-x64.exe"
    shutil.copy2(executable, target)
    target.with_suffix(".exe.sha256").write_text(
        f"{hashlib.sha256(content).hexdigest()}  {target.name}\n", encoding="ascii")
    shutil.copy2(report, release / "windows-self-test.json")
    print(f"Built and smoke-tested: {target}")
    print("Windows KakaoTalk sending is NOT implemented; this build supports UI and diagnostics only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
