@echo off
setlocal
cd /d "%~dp0.."
py -3.12 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12 x64 from python.org, including the py launcher.
  goto failed
)
if not exist ".venv-windows-build\Scripts\python.exe" py -3.12 -m venv .venv-windows-build
if errorlevel 1 goto failed
.venv-windows-build\Scripts\python.exe -m pip install --require-hashes -r requirements/windows.txt
if errorlevel 1 goto failed
.venv-windows-build\Scripts\python.exe -m pytest -q
if errorlevel 1 goto failed
.venv-windows-build\Scripts\python.exe scripts\build_windows.py
if errorlevel 1 goto failed
echo.
echo Output: dist\releases\0.1.0\Kakao-Friend-Sender-0.1.0-windows-x64.exe
echo Windows KakaoTalk sending is not supported yet. This build is for UI and diagnostics.
if not defined CI pause
exit /b 0
:failed
echo Build failed. Review the error above; no release EXE was confirmed.
if not defined CI pause
exit /b 1
