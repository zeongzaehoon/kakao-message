//! Tauri handles distribution; the existing Qt application owns the GUI.
//! exec replaces this launcher so closing Qt leaves no background launcher.
use std::path::{Path, PathBuf};
use std::process::Command;

fn runtime_path(executable: &Path) -> PathBuf {
    let directory = executable.parent().expect("executable has a parent");
    if directory.file_name().is_some_and(|name| name == "MacOS") {
        directory.join("KakaoSenderRuntime")
    } else {
        Path::new(env!("CARGO_MANIFEST_DIR")).join(
            "../build/tauri-runtime/dist/KakaoSenderRuntime.app/Contents/MacOS/KakaoSenderRuntime",
        )
    }
}

fn main() {
    #[cfg(not(target_os = "macos"))]
    compile_error!("Use scripts/build_windows.py for Windows packaging.");

    #[cfg(target_os = "macos")]
    {
        use std::os::unix::process::CommandExt;
        let executable = std::env::current_exe().expect("cannot locate launcher");
        let error = Command::new(runtime_path(&executable))
            .args(std::env::args_os().skip(1))
            .exec();
        eprintln!("Kakao Friend Sender could not start: {error}");
        // Finder launches have no terminal, so show a fixed, actionable error.
        let _ = Command::new("/usr/bin/osascript")
            .args(["-e", "display alert \"Kakao Friend Sender를 실행할 수 없습니다\" message \"앱에 포함된 실행 파일을 열지 못했습니다. DMG에서 앱을 다시 복사해 주세요.\" as critical"])
            .status();
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relocated_app_resolves_its_own_runtime() {
        let path = runtime_path(Path::new(
            "/Volumes/Test Disk/Kakao Friend Sender.app/Contents/MacOS/kakao-friend-sender",
        ));
        assert_eq!(
            path,
            Path::new(
                "/Volumes/Test Disk/Kakao Friend Sender.app/Contents/MacOS/KakaoSenderRuntime"
            )
        );
    }
}
