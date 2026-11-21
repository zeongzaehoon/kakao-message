#[cfg(target_os = "macos")]
mod ax;
mod core;
#[cfg(target_os = "macos")]
mod installer;
#[cfg(any(target_os = "macos", test))]
mod live_check;
#[cfg(target_os = "macos")]
mod native;
mod session;
#[cfg(any(target_os = "macos", test))]
mod targets;
mod ui;
mod verification;
use std::path::Path;
fn main() {
    let args: Vec<String> = std::env::args().collect();
    #[cfg(target_os = "macos")]
    if args.get(1).is_some_and(|s| s == "--self-chat-test") {
        if args.len() != 4 {
            eprintln!("사용법: --self-chat-test 본인이름 결과파일 (본인 방에 글·사진 실제 전송)");
            std::process::exit(1);
        }
        let result = objc2::rc::autoreleasepool(|_| live_check::run(&args[2]));
        let report = result.unwrap_or_else(|error| serde_json::json!({"ok":false,"test_started":false,"error":error,"input":0,"sent":0}));
        let ok = report["ok"] == true;
        if let Err(error) = std::fs::write(&args[3], serde_json::to_vec_pretty(&report).unwrap()) {
            eprintln!("결과 파일 저장 실패: {error}. 자동 재시도하지 마세요. 결과: {report}");
            std::process::exit(1);
        }
        std::process::exit(if ok { 0 } else { 1 });
    }
    #[cfg(target_os = "macos")]
    if args.get(1).is_some_and(|s| s == "--identity-check") {
        let result = objc2::rc::autoreleasepool(|_| {
            native::Native::connect(None).and_then(|mut native| native.identity_probe())
        });
        let ok = result.as_ref().is_ok_and(|report| report["ok"] == true);
        let report = result.unwrap_or_else(
            |error| serde_json::json!({"ok":false,"error":error,"input":0,"sent":0}),
        );
        if let Some(path) = args.get(2) {
            if std::fs::write(path, serde_json::to_vec_pretty(&report).unwrap()).is_err() {
                std::process::exit(1);
            }
        } else {
            println!("{report}");
        }
        std::process::exit(if ok { 0 } else { 1 });
    }
    if args.get(1).is_some_and(|s| s == "--self-test") {
        let result = verification::self_test();
        let success = result.is_ok();
        let report = match result {
            Ok(value) => value,
            Err(e) => serde_json::json!({"ok":false,"error":e}),
        };
        if let Some(path) = args.get(2) {
            if std::fs::write(path, serde_json::to_vec_pretty(&report).unwrap()).is_err() {
                std::process::exit(1);
            }
        } else {
            println!("{report}");
        }
        std::process::exit(if success { 0 } else { 1 });
    }
    if args.get(1).is_some_and(|s| s == "--chat-list-check") {
        #[cfg(target_os = "macos")]
        {
            let start = std::time::Instant::now();
            let result = objc2::rc::autoreleasepool(|_| {
                native::Native::connect(None)
                    .and_then(|mut d| d.list(&core::Stop::default(), |_, _| {}))
            });
            let ok = result.is_ok();
            let report = match result {
                Ok(cat) => {
                    serde_json::json!({"ok":true,"count":cat.rooms.len(),"catalog":cat,"elapsed_seconds":start.elapsed().as_secs_f64(),"sent":0})
                }
                Err(e) => serde_json::json!({"ok":false,"error":e,"sent":0}),
            };
            if let Some(path) = args.get(2) {
                let _ =
                    std::fs::write(Path::new(path), serde_json::to_vec_pretty(&report).unwrap());
            }
            std::process::exit(if ok { 0 } else { 1 });
        }
        #[cfg(not(target_os = "macos"))]
        {
            eprintln!("Windows 전송 미지원");
            std::process::exit(1);
        }
    }
    if args.get(1).is_some_and(|s| s == "--version") {
        println!("{}", env!("CARGO_PKG_VERSION"));
        return;
    }
    if args.get(1).is_some_and(|s| s == "--help") {
        println!("Kakao Friend Sender\n--self-test FILE\n--ui-self-test FILE\n--chat-list-check FILE\n--identity-check FILE (macOS, read only)\n--self-chat-test SELF_NAME FILE (macOS, sends text and photo to self)\n--installation-info (macOS)\n--version");
        return;
    }
    #[cfg(target_os = "macos")]
    if args.get(1).is_some_and(|s| s == "--installation-info") {
        println!("{}", installer::info());
        return;
    }
    let smoke = if args.get(1).is_some_and(|s| s == "--ui-self-test") {
        args.get(2).map(std::path::PathBuf::from)
    } else {
        None
    };
    #[cfg(target_os = "macos")]
    if smoke.is_none() && installer::handle_launch() {
        return;
    }
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_title("Kakao Friend Sender")
            .with_title_shown(false)
            .with_titlebar_shown(false)
            .with_fullsize_content_view(true)
            .with_inner_size(
                if smoke.is_some() && args.get(4).is_some_and(|s| s == "compact") {
                    [940., 700.]
                } else {
                    [1120., 800.]
                },
            )
            .with_min_inner_size([940., 700.]),
        ..Default::default()
    };
    if let Err(e) = eframe::run_native(
        "Kakao Friend Sender",
        options,
        Box::new(move |cc| {
            let mut app = ui::App::new(cc, smoke);
            app.self_test_view(args.get(3).map(String::as_str).unwrap_or("composer"));
            Ok(Box::new(app))
        }),
    ) {
        eprintln!("앱 실행 실패: {e}");
        std::process::exit(1);
    }
}
