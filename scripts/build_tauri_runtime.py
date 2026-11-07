"""Freeze Python/Qt; Tauri merges its payload into a single macOS app bundle."""
from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "darwin":
        print("Tauri 패키징은 macOS에서 실행해 주세요.", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    output = root / "build" / "tauri-runtime"
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed", "--onedir", "--name", "KakaoSenderRuntime",
        "--distpath", str(output / "dist"),
        "--workpath", str(output / "work"), "--specpath", str(output),
        "--paths", str(root / "src"),
        "--osx-bundle-identifier", "local.kakaofriendsender.prototype.runtime",
        "--icon", str(root / "src-tauri" / "icons" / "icon.icns"),
        "--hidden-import", "ApplicationServices", "--hidden-import", "AppKit",
        "--hidden-import", "CoreFoundation",
        str(root / "scripts" / "launcher.py"),
    ]
    subprocess.run(command, cwd=root, check=True)
    rust_info = subprocess.check_output(["rustc", "-vV"], text=True)
    target = next(line.removeprefix("host: ") for line in rust_info.splitlines() if line.startswith("host: "))
    shutil.copy2(
        output / "dist/KakaoSenderRuntime.app/Contents/MacOS/KakaoSenderRuntime",
        output / f"KakaoSenderRuntime-{target}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
