@echo off
setlocal
cd /d "%~dp0.."
where cargo >nul 2>&1
if errorlevel 1 (
  echo Install Rust stable with the MSVC toolchain and Visual Studio C++ Build Tools.
  goto failed
)
cargo test --locked --manifest-path src-tauri/Cargo.toml
if errorlevel 1 goto failed
cargo build --release --locked --manifest-path src-tauri/Cargo.toml
if errorlevel 1 goto failed
powershell -NoProfile -Command "$m = cargo metadata --no-deps --format-version 1 --manifest-path src-tauri/Cargo.toml | ConvertFrom-Json; if ($LASTEXITCODE -ne 0) { exit 1 }; $v = ($m.packages | Where-Object name -eq 'kakao-friend-sender').version; $out = Join-Path 'dist/releases' $v; New-Item -ItemType Directory -Force $out | Out-Null; $exe = Join-Path $out ('Kakao-Friend-Sender-' + $v + '-windows-x64.exe'); Copy-Item 'src-tauri/target/release/kakao-friend-sender.exe' $exe; & $exe --self-test (Join-Path $out 'windows-self-test.json'); if ($LASTEXITCODE -ne 0) { exit 1 }; $hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower(); ($hash + '  ' + (Split-Path $exe -Leaf)) | Set-Content -Encoding ascii (Join-Path $out 'SHA256SUMS.txt')"
if errorlevel 1 goto failed
echo Output: dist\releases\version\
echo Windows KakaoTalk sending is not supported. This is a native Rust UI build.
if not defined CI pause
exit /b 0
:failed
echo Build failed. No release executable was confirmed.
if not defined CI pause
exit /b 1
