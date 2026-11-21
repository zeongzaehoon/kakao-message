//! Local DMG installation only. No network update or application-data migration.
use crate::core::Result;
use objc2_app_kit::NSWorkspace;
use rfd::{MessageButtons, MessageDialog, MessageDialogResult, MessageLevel};
use std::{
    fs::{self, File, OpenOptions},
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
    path::{Path, PathBuf},
    process::Command,
};

const APP: &str = "Kakao Friend Sender.app";
const IDENTIFIER: &str = "local.kakaofriendsender.prototype";
const DESTINATION: &str = "/Applications/Kakao Friend Sender.app";

fn bundle(executable: &Path) -> Option<PathBuf> {
    let macos = executable.parent()?;
    let contents = macos.parent()?;
    let app = contents.parent()?;
    (macos.file_name()? == "MacOS"
        && contents.file_name()? == "Contents"
        && app.extension()? == "app")
        .then(|| app.to_path_buf())
}

fn from_disk_image(app: &Path) -> bool {
    app.starts_with("/Volumes")
        || app
            .components()
            .any(|part| part.as_os_str() == "AppTranslocation")
}

fn command(program: &str, args: &[&std::ffi::OsStr]) -> Result<String> {
    let output = Command::new(program)
        .args(args)
        .output()
        .map_err(|e| format!("{program} 실행 실패: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "{program}: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn plist(app: &Path, key: &str) -> Result<String> {
    command(
        "/usr/libexec/PlistBuddy",
        &[
            "-c".as_ref(),
            format!("Print :{key}").as_ref(),
            app.join("Contents/Info.plist").as_os_str(),
        ],
    )
}

fn version(value: &str) -> Result<Vec<u64>> {
    let parts: Vec<_> = value.split('.').map(str::parse::<u64>).collect();
    if parts.len() != 3 || parts.iter().any(|p| p.is_err()) {
        return Err(format!("버전을 확인할 수 없습니다: {value}"));
    }
    Ok(parts.into_iter().map(std::result::Result::unwrap).collect())
}

fn check_destination(destination: &Path) -> Result<Option<String>> {
    match fs::symlink_metadata(destination) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.to_string()),
        Ok(meta) => {
            if !meta.is_dir() || meta.file_type().is_symlink() {
                return Err("설치 경로가 앱 폴더가 아닙니다. 기존 파일을 확인하세요.".into());
            }
            if plist(destination, "CFBundleIdentifier")? != IDENTIFIER {
                return Err("같은 이름의 다른 앱이 있어 교체하지 않았습니다.".into());
            }
            let installed = plist(destination, "CFBundleShortVersionString")?;
            if version(&installed)? > version(env!("CARGO_PKG_VERSION"))? {
                return Err(format!(
                    "이미 더 최신 버전({installed})이 설치되어 있습니다. 이 DMG로 낮추지 않습니다."
                ));
            }
            Ok(Some(installed))
        }
    }
}

fn running() -> bool {
    objc2::rc::autoreleasepool(|_| {
        NSWorkspace::sharedWorkspace()
            .runningApplications()
            .iter()
            .any(|app| {
                if app.processIdentifier() == std::process::id() as i32 || app.isTerminated() {
                    return false;
                }
                app.bundleIdentifier()
                    .is_some_and(|id| id.to_string() == IDENTIFIER)
                    || app
                        .bundleURL()
                        .and_then(|url| url.path())
                        .is_some_and(|path| path.to_string() == DESTINATION)
                    || app
                        .executableURL()
                        .and_then(|url| url.path())
                        .is_some_and(|path| {
                            let path = PathBuf::from(path.to_string());
                            path.file_name().is_some_and(|name| {
                                name == "KakaoSenderRuntime" || name == "kakao-friend-sender"
                            })
                        })
            })
    })
}

fn confirm(description: &str, button: &str) -> bool {
    MessageDialog::new()
        .set_title("Kakao Friend Sender 설치")
        .set_description(description)
        .set_buttons(MessageButtons::OkCancelCustom(button.into(), "취소".into()))
        .show()
        == MessageDialogResult::Custom(button.into())
}

fn error(message: &str) {
    MessageDialog::new()
        .set_title("설치하지 못했습니다")
        .set_level(MessageLevel::Error)
        .set_description(message)
        .show();
}

// flock is released by the OS even if the installer crashes. Keep the lock file
// in place so another installer can never lock a different inode at this path.
struct InstallLock {
    _file: File,
}
impl InstallLock {
    fn acquire(parent: &Path) -> Result<Self> {
        unsafe extern "C" {
            fn flock(fd: i32, operation: i32) -> i32;
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(0x100) // macOS O_NOFOLLOW: do not follow a lock-file symlink.
            .open(parent.join(".kakao-friend-sender.install.lock"))
            .map_err(|e| format!("응용 프로그램 폴더에 쓰기 권한이 필요합니다: {e}"))?;
        if unsafe { flock(file.as_raw_fd(), 2 | 4) } != 0 {
            return Err("다른 설치가 진행 중입니다. 해당 설치가 끝난 뒤 다시 실행하세요.".into());
        }
        Ok(Self { _file: file })
    }
}

fn validate(app: &Path) -> Result<()> {
    if plist(app, "CFBundleIdentifier")? != IDENTIFIER
        || plist(app, "CFBundleShortVersionString")? != env!("CARGO_PKG_VERSION")
    {
        return Err("설치할 앱의 식별자·버전이 일치하지 않습니다.".into());
    }
    command(
        "/usr/bin/codesign",
        &[
            "--verify".as_ref(),
            "--deep".as_ref(),
            "--strict".as_ref(),
            app.as_os_str(),
        ],
    )?;
    Ok(())
}

// Only the app bundle is touched. Settings, journals and user drafts are never
// read or removed. Keep the old bundle until the new one has been launched.
fn replace(
    destination: &Path,
    transaction: &Path,
    copy_and_check: impl FnOnce(&Path) -> Result<()>,
    before_replace: impl FnOnce() -> Result<()>,
    launch: impl FnOnce(&Path) -> Result<()>,
) -> Result<()> {
    fs::create_dir(transaction).map_err(|e| {
        format!("설치 임시 폴더를 만들 수 없습니다: {e}\n이전 설치가 중단됐다면 {}/previous.app을 확인하세요. 기존 파일은 삭제하지 않았습니다.", transaction.display())
    })?;
    let staged = transaction.join(APP);
    let previous = transaction.join("previous.app");
    if let Err(e) = copy_and_check(&staged).and_then(|_| before_replace()) {
        let _ = fs::remove_dir_all(transaction);
        return Err(e);
    }
    let had_previous = destination.exists();
    if had_previous {
        if let Err(e) = fs::rename(destination, &previous) {
            let _ = fs::remove_dir_all(transaction);
            return Err(format!("기존 앱을 보관하지 못했습니다: {e}"));
        }
    }
    let install = fs::rename(&staged, destination)
        .map_err(|e| format!("새 앱으로 교체하지 못했습니다: {e}"))
        .and_then(|_| launch(destination));
    if let Err(e) = install {
        // Move the failed new bundle aside before restoring the old bundle.
        let rollback = (|| -> std::io::Result<()> {
            if destination.exists() {
                fs::rename(destination, transaction.join("failed.app"))?;
            }
            if had_previous {
                fs::rename(&previous, destination)?;
            }
            Ok(())
        })();
        if let Err(restore) = rollback {
            return Err(format!(
                "{e}\n자동 복구 실패: {restore}\n이전 앱 보관 경로: {}",
                previous.display()
            ));
        }
        let _ = fs::remove_dir_all(transaction);
        return Err(format!("{e}\n설치 전 상태로 복구했습니다."));
    }
    // A cleanup failure must not turn a successful upgrade into a rollback.
    if let Err(e) = fs::remove_dir_all(transaction) {
        eprintln!(
            "업데이트 완료, 이전 앱 정리 실패 ({}): {e}",
            transaction.display()
        );
    }
    Ok(())
}

fn install(source: &Path) -> Result<()> {
    let destination = Path::new(DESTINATION);
    let parent = destination.parent().unwrap();
    let _lock = InstallLock::acquire(parent)?;
    check_destination(destination)?;
    validate(source)?;
    replace(
        destination,
        &parent.join(".kakao-friend-sender.update.noindex"),
        |staged| {
            command("/usr/bin/ditto", &[source.as_os_str(), staged.as_os_str()])?;
            validate(staged)
        },
        || {
            check_destination(destination)?;
            if running() {
                return Err(
                    "기존 앱이 실행 중입니다. 작성 내용을 보관하고 앱을 종료한 뒤 다시 설치하세요."
                        .into(),
                );
            }
            Ok(())
        },
        |installed| {
            command("/usr/bin/open", &["-n".as_ref(), installed.as_os_str()])?;
            Ok(())
        },
    )
}

pub fn info() -> serde_json::Value {
    let source = std::env::current_exe().ok().and_then(|exe| bundle(&exe));
    serde_json::json!({
        "source": source,
        "installer": source.as_ref().is_some_and(|app| from_disk_image(app)),
        "destination": DESTINATION,
        "version": env!("CARGO_PKG_VERSION"),
        "installed_version": plist(Path::new(DESTINATION), "CFBundleShortVersionString").ok(),
        "changed": false,
    })
}

/// Returns true when normal sender startup should be skipped (also on cancel).
pub fn handle_launch() -> bool {
    let Some(source) = std::env::current_exe().ok().and_then(|exe| bundle(&exe)) else {
        return false;
    };
    if !from_disk_image(&source) {
        return false;
    }
    let installed = match check_destination(Path::new(DESTINATION)) {
        Ok(installed) => installed,
        Err(e) => {
            error(&e);
            return true;
        }
    };
    let (action, heading) = match installed {
        Some(v) => (
            "업데이트",
            format!("기존 {v} → {}", env!("CARGO_PKG_VERSION")),
        ),
        None => ("설치", format!("버전 {} 설치", env!("CARGO_PKG_VERSION"))),
    };
    if !confirm(&format!("{heading}\n\n위치: {DESTINATION}\n설정과 전송 이력은 유지합니다. 설치 후 새 앱을 실행합니다.\n작성 중인 내용은 먼저 따로 보관해 주세요."), action) {
        return true;
    }
    while running() {
        if !confirm("기존 Kakao Friend Sender가 실행 중입니다.\n작성 내용을 보관하고 기존 앱을 완전히 종료한 뒤 ‘다시 확인’을 누르세요.\n앱을 강제 종료하지 않습니다.", "다시 확인") {
            return true;
        }
    }
    if let Err(e) = install(&source) {
        error(&e);
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT: AtomicUsize = AtomicUsize::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "kakao-install-test-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn destination(&self) -> PathBuf {
            self.0.join(APP)
        }
        fn transaction(&self) -> PathBuf {
            self.0.join("transaction")
        }
        fn existing(&self) {
            fs::create_dir(self.destination()).unwrap();
            fs::write(self.destination().join("version"), "old").unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    fn copy(path: &Path) -> Result<()> {
        fs::create_dir(path).map_err(|e| e.to_string())?;
        fs::write(path.join("version"), "new").map_err(|e| e.to_string())
    }
    #[test]
    fn launch_detection_excludes_installed_and_development_app() {
        for path in [
            "/Applications/Kakao Friend Sender.app",
            "/tmp/build/Kakao Friend Sender.app",
        ] {
            assert!(!from_disk_image(Path::new(path)));
        }
        assert!(from_disk_image(Path::new(
            "/Volumes/Kakao Friend Sender/Kakao Friend Sender.app"
        )));
        assert!(from_disk_image(Path::new(
            "/private/var/folders/test/AppTranslocation/id/d/Kakao Friend Sender.app"
        )));
        assert!(!from_disk_image(Path::new("/VolumesOther/app.app")));
        assert!(bundle(Path::new("/tmp/target/debug/kakao-friend-sender")).is_none());
        assert_eq!(
            bundle(Path::new("/Volumes/Disk/a.app/Contents/MacOS/app")),
            Some(PathBuf::from("/Volumes/Disk/a.app"))
        );
    }
    #[test]
    fn numeric_version_comparison() {
        assert!(version("0.2.10").unwrap() > version("0.2.9").unwrap());
        assert!(version("0.2.1-beta").is_err());
        assert!(version("0.2").is_err());
    }
    #[test]
    fn fresh_install_and_upgrade_preserve_data() {
        for existing in [false, true] {
            let f = Fixture::new();
            if existing {
                f.existing();
            }
            fs::write(f.0.join("attempts.sqlite3"), "history").unwrap();
            replace(
                &f.destination(),
                &f.transaction(),
                copy,
                || Ok(()),
                |path| {
                    assert_eq!(fs::read_to_string(path.join("version")).unwrap(), "new");
                    Ok(())
                },
            )
            .unwrap();
            assert_eq!(
                fs::read_to_string(f.0.join("attempts.sqlite3")).unwrap(),
                "history"
            );
            assert!(!f.transaction().exists());
        }
    }
    #[test]
    fn launch_failure_rolls_back_existing_and_fresh_install() {
        for existing in [false, true] {
            let f = Fixture::new();
            if existing {
                f.existing();
            }
            assert!(replace(
                &f.destination(),
                &f.transaction(),
                copy,
                || Ok(()),
                |_| Err("launch failed".into())
            )
            .is_err());
            assert_eq!(f.destination().exists(), existing);
            if existing {
                assert_eq!(
                    fs::read_to_string(f.destination().join("version")).unwrap(),
                    "old"
                );
            }
            assert!(!f.transaction().exists());
        }
    }
    #[test]
    fn copy_or_validation_failure_leaves_existing_app() {
        let f = Fixture::new();
        f.existing();
        assert!(replace(
            &f.destination(),
            &f.transaction(),
            |path| {
                copy(path)?;
                Err("invalid signature".into())
            },
            || Ok(()),
            |_| panic!("must not launch")
        )
        .is_err());
        assert_eq!(
            fs::read_to_string(f.destination().join("version")).unwrap(),
            "old"
        );
        assert!(!f.transaction().exists());
    }
    #[test]
    fn running_app_detected_after_copy_prevents_replacement() {
        let f = Fixture::new();
        f.existing();
        assert!(replace(
            &f.destination(),
            &f.transaction(),
            copy,
            || Err("app reopened".into()),
            |_| panic!("must not launch")
        )
        .is_err());
        assert_eq!(
            fs::read_to_string(f.destination().join("version")).unwrap(),
            "old"
        );
    }
    #[test]
    fn interrupted_transaction_is_not_deleted() {
        let f = Fixture::new();
        fs::create_dir(f.transaction()).unwrap();
        fs::write(f.transaction().join("previous.app"), "old").unwrap();
        assert!(replace(
            &f.destination(),
            &f.transaction(),
            copy,
            || Ok(()),
            |_| Ok(())
        )
        .is_err());
        assert_eq!(
            fs::read_to_string(f.transaction().join("previous.app")).unwrap(),
            "old"
        );
    }
    #[test]
    fn install_lock_serializes_and_releases() {
        let f = Fixture::new();
        let lock = InstallLock::acquire(&f.0).unwrap();
        assert!(InstallLock::acquire(&f.0).is_err());
        drop(lock);
        assert!(InstallLock::acquire(&f.0).is_ok());
    }
}
