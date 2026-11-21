use crate::core::*;
use std::time::Instant;
#[derive(Default)]
struct Fake {
    opened: Vec<String>,
    sent: usize,
    closed: usize,
    fail_prepare: bool,
    fail_send: bool,
    journal_alias: Option<String>,
}
impl Backend for Fake {
    fn journal_key(&self, room: &Room) -> Result<String> {
        Ok(self
            .journal_alias
            .clone()
            .unwrap_or_else(|| room.key.clone()))
    }
    fn prepare(&mut self, r: &Room, s: &Stop) -> Result<()> {
        check(s)?;
        if self.fail_prepare {
            return Err("초안 있음".into());
        }
        self.opened.push(r.name.clone());
        Ok(())
    }
    fn text(&mut self, _: &Room, _: &str, _: &Stop) -> Result<()> {
        self.sent += 1;
        if self.fail_send {
            Err("전송 응답 없음".into())
        } else {
            Ok(())
        }
    }
    fn photo(&mut self, r: &Room, _: &Photo, s: &Stop) -> Result<()> {
        self.text(r, "", s)
    }
    fn finish(&mut self, _: &Room, _: &Stop) -> Result<()> {
        self.closed += 1;
        Ok(())
    }
}
fn plan(size: usize) -> Plan {
    Plan {
        pid: 123,
        rooms: (0..size)
            .map(|i| Room {
                key: format!("room-{i}"),
                name: format!("테스트 방 {i:05}"),
                selectable: true,
                note: String::new(),
            })
            .collect(),
        message: "테스트 👋\n두 번째 줄".into(),
        photos: vec![],
        live: true,
        interval: 0.,
    }
}
pub fn self_test() -> Result<serde_json::Value> {
    let start = Instant::now();
    let p = plan(10000);
    p.validate()?;
    let directory =
        std::env::temp_dir().join(format!("kakao-rust-selftest-{}", std::process::id()));
    std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let result = (|| {
        let journal = Journal::open(&directory.join("attempts.sqlite3"))?;
        let mut fake = Fake::default();
        let mut sample = p.clone();
        sample.rooms.truncate(100);
        execute(&sample, &mut fake, &journal, &Stop::default(), |_| {})?;
        if fake.sent != 100 || fake.closed != 100 {
            return Err("순차 전송 모의 검사 실패".into());
        }
        execute(&sample, &mut fake, &journal, &Stop::default(), |_| {})?;
        if fake.sent != 100 {
            return Err("중복 전송 차단 실패".into());
        }
        Ok(
            serde_json::json!({"ok":true,"version":env!("CARGO_PKG_VERSION"),"runtime":"rust","python_required":false,"catalog_rooms":p.rooms.len(),"mock_sent":fake.sent,"real_sent":0,"elapsed_seconds":start.elapsed().as_secs_f64()}),
        )
    })();
    let _ = std::fs::remove_dir_all(directory);
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::Ordering;
    fn memory() -> Journal {
        Journal::open(std::path::Path::new(":memory:")).unwrap()
    }
    #[test]
    fn large_catalog() {
        assert!(self_test().is_ok());
    }
    #[test]
    fn duplicates_are_blocked() {
        let mut p = plan(2);
        p.rooms[1] = p.rooms[0].clone();
        assert!(p.validate().is_err());
    }
    #[test]
    fn changing_session_token_keeps_existing_send_history() {
        let mut p = plan(1);
        let j = memory();
        let mut b = Fake {
            journal_alias: Some("legacy-room".into()),
            ..Default::default()
        };
        execute(&p, &mut b, &j, &Stop::default(), |_| {}).unwrap();
        p.rooms[0].key = "new-session-token".into();
        execute(&p, &mut b, &j, &Stop::default(), |_| {}).unwrap();
        assert_eq!(b.sent, 1);
        assert_eq!(b.opened.len(), 1);
    }
    #[test]
    fn prepare_failure_releases_reservation() {
        let p = plan(1);
        let j = memory();
        let mut b = Fake {
            fail_prepare: true,
            ..Default::default()
        };
        assert!(execute(&p, &mut b, &j, &Stop::default(), |_| {}).is_err());
        assert_eq!(
            j.state(&Journal::identity(
                &p.scope(),
                &p.rooms[0].key,
                &p.message,
                None
            )),
            None
        );
        assert_eq!(b.sent, 0);
    }
    #[test]
    fn send_failure_is_not_retried() {
        let p = plan(2);
        let j = memory();
        let mut b = Fake {
            fail_send: true,
            ..Default::default()
        };
        assert!(execute(&p, &mut b, &j, &Stop::default(), |_| {}).is_err());
        let id = Journal::identity(&p.scope(), &p.rooms[0].key, &p.message, None);
        assert_eq!(j.state(&id).as_deref(), Some("uncertain"));
        assert_eq!(b.sent, 1);
    }
    #[test]
    fn dry_run_does_not_send() {
        let mut p = plan(10);
        p.live = false;
        let mut b = Fake::default();
        execute(&p, &mut b, &memory(), &Stop::default(), |_| {}).unwrap();
        assert_eq!(b.sent, 0);
        assert_eq!(b.opened.len(), 10);
    }
    #[test]
    fn cancelled_before_open() {
        let stop = Stop::default();
        stop.store(true, Ordering::Relaxed);
        let mut b = Fake::default();
        assert!(execute(&plan(1), &mut b, &memory(), &stop, |_| {}).is_err());
        assert!(b.opened.is_empty());
    }
    #[test]
    fn invalid_interval() {
        let mut p = plan(1);
        p.interval = f64::NAN;
        assert!(p.validate().is_err());
    }
    #[test]
    fn canonical_unicode() {
        assert_eq!(canonical(" 가 "), "가");
    }
}

#[cfg(test)]
mod compatibility_tests {
    use super::*;
    use std::{path::Path, sync::atomic::Ordering, time::Duration};
    #[test]
    fn old_python_message_journal_key() {
        assert_eq!(
            Journal::identity(
                "darwin:conversations:123",
                "room-1",
                "테스트 👋\n두 번째 줄",
                None
            ),
            "b27ecf0eede61190ac95d7d74e6ffb8421a8a1a78506b473c43ab6ac98a1ee3a"
        );
    }
    #[test]
    fn old_python_photo_journal_key() {
        assert_eq!(
            Journal::identity("darwin:conversations:123", "room-1", "무시", Some("abc123")),
            "57fded503a12068462b8c9dfadd027018c337308cd59b185355e7de3d482b3aa"
        );
    }
    #[test]
    fn pending_crash_record_never_resends() {
        let p = plan(1);
        let j = Journal::open(Path::new(":memory:")).unwrap();
        let id = Journal::identity(&p.scope(), &p.rooms[0].key, &p.message, None);
        j.reserve(&id).unwrap();
        let mut fake = Fake::default();
        execute(&p, &mut fake, &j, &Stop::default(), |_| {}).unwrap();
        assert_eq!(fake.sent, 0);
        assert_eq!(fake.closed, 0);
        assert!(fake.opened.is_empty());
    }
    #[test]
    fn uncertain_record_is_preserved_after_new_run() {
        let p = plan(1);
        let j = Journal::open(Path::new(":memory:")).unwrap();
        let id = Journal::identity(&p.scope(), &p.rooms[0].key, &p.message, None);
        j.reserve(&id).unwrap();
        j.finish(&id, "uncertain").unwrap();
        let mut fake = Fake::default();
        execute(&p, &mut fake, &j, &Stop::default(), |_| {}).unwrap();
        assert_eq!(fake.sent, 0);
        assert_eq!(j.state(&id).as_deref(), Some("uncertain"));
    }
    #[test]
    fn cancellation_interrupts_interval() {
        let mut p = plan(2);
        p.interval = 5.;
        let stop = Stop::default();
        let signal = stop.clone();
        let j = Journal::open(Path::new(":memory:")).unwrap();
        let mut b = Fake::default();
        let start = Instant::now();
        let t = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(40));
            signal.store(true, Ordering::Relaxed);
        });
        assert!(execute(&p, &mut b, &j, &stop, |_| {}).is_err());
        t.join().unwrap();
        assert!(start.elapsed() < Duration::from_secs(1));
        assert_eq!(b.sent, 1);
    }
    #[test]
    fn disabled_room_cannot_send() {
        let mut p = plan(1);
        p.rooms[0].selectable = false;
        assert!(p.validate().is_err());
    }
    #[test]
    fn empty_content_cannot_send() {
        let mut p = plan(1);
        p.message = " \n ".into();
        assert!(p.validate().is_err());
    }
    #[test]
    fn unicode_length_limit_counts_characters() {
        let mut p = plan(1);
        p.message = "가".repeat(10000);
        assert!(p.validate().is_ok());
        p.message.push('가');
        assert!(p.validate().is_err());
    }
    #[test]
    fn photo_formats_and_immutable_bytes() {
        for format in [
            image::ImageFormat::Png,
            image::ImageFormat::Jpeg,
            image::ImageFormat::WebP,
            image::ImageFormat::Bmp,
        ] {
            let path = std::env::temp_dir().join(format!(
                "kakao-photo-{}-{}.img",
                std::process::id(),
                format as u32
            ));
            let pixels = image::RgbImage::from_pixel(120, 80, image::Rgb([254, 229, 0]));
            image::DynamicImage::ImageRgb8(pixels)
                .save_with_format(&path, format)
                .unwrap();
            let photo = Photo::load(&path).unwrap();
            std::fs::remove_file(&path).unwrap();
            assert_eq!((photo.width, photo.height), (120, 80));
            assert!(photo.png.starts_with(b"\x89PNG\r\n\x1a\n"));
            assert_eq!(photo.hash, digest(&*photo.png));
            let mut p = plan(1);
            p.photos = vec![photo.clone(), photo];
            assert!(p.validate().is_err());
        }
    }
    #[test]
    fn corrupt_photo_rejected() {
        let path = std::env::temp_dir().join(format!("kakao-corrupt-{}.png", std::process::id()));
        std::fs::write(&path, b"not an image").unwrap();
        assert!(Photo::load(&path).is_err());
        std::fs::remove_file(path).unwrap();
    }
}
