use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use unicode_normalization::UnicodeNormalization;
pub type Result<T> = std::result::Result<T, String>;
pub type Stop = Arc<AtomicBool>;
pub fn canonical(s: &str) -> String {
    s.trim().nfc().collect()
}
pub fn digest(s: impl AsRef<[u8]>) -> String {
    format!("{:x}", Sha256::digest(s.as_ref()))
}
pub fn check(stop: &Stop) -> Result<()> {
    if stop.load(Ordering::Relaxed) {
        Err("사용자가 중지했습니다.".into())
    } else {
        Ok(())
    }
}
pub fn wait(stop: &Stop, duration: Duration) -> Result<()> {
    let start = Instant::now();
    while start.elapsed() < duration {
        check(stop)?;
        std::thread::sleep(Duration::from_millis(20).min(duration.saturating_sub(start.elapsed())));
    }
    check(stop)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Room {
    pub key: String,
    pub name: String,
    pub selectable: bool,
    pub note: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Catalog {
    pub pid: i32,
    pub rooms: Vec<Room>,
    pub complete: bool,
    pub note: String,
}
#[derive(Clone)]
pub struct Photo {
    pub name: String,
    pub png: Arc<Vec<u8>>,
    pub rgba: Arc<Vec<u8>>,
    pub width: u32,
    pub height: u32,
    pub hash: String,
    pub source_bytes: usize,
    pub original_dimensions: (u32, u32),
    pub sent_dimensions: (u32, u32),
}
pub const PHOTO_BYTES_LIMIT: usize = 20 * 1024 * 1024;
const PHOTO_INPUT_LIMIT: usize = 128 * 1024 * 1024;
const PHOTO_DECODE_PIXELS: u64 = 64_000_000;
const PHOTO_WORKING_PIXELS: u64 = 24_000_000;

/// Normalize once when attaching, then reuse the same immutable PNG for every room.
/// Smaller photos use the original encoder path to preserve their journal hashes.
fn fit_photo(
    mut img: image::DynamicImage,
    byte_limit: usize,
    pixel_limit: u64,
) -> Result<(image::DynamicImage, Vec<u8>)> {
    let pixels = u64::from(img.width()) * u64::from(img.height());
    if pixels > pixel_limit {
        let ratio = (pixel_limit as f64 / pixels as f64).sqrt();
        let width = ((img.width() as f64 * ratio).floor() as u32).max(1);
        let height = ((img.height() as f64 * ratio).floor() as u32).max(1);
        let width = width.min((pixel_limit / u64::from(height)).max(1) as u32);
        let height = height.min((pixel_limit / u64::from(width)).max(1) as u32);
        img = img.resize_exact(width, height, image::imageops::FilterType::Triangle);
    }
    loop {
        let mut png = std::io::Cursor::new(Vec::new());
        img.write_to(&mut png, image::ImageFormat::Png)
            .map_err(|e| e.to_string())?;
        let png = png.into_inner();
        if png.len() <= byte_limit {
            return Ok((img, png));
        }
        if img.width() == 1 && img.height() == 1 {
            return Err("사진을 전송 용량에 맞게 줄일 수 없습니다.".into());
        }
        // Pixel count scales with the square of each dimension. Leave headroom
        // for PNG overhead; always shrink even when just over the size limit.
        let ratio = ((byte_limit as f64 / png.len() as f64).sqrt() * 0.9).min(0.85);
        drop(png);
        img = shrink_photo(&img, ratio);
    }
}

fn shrink_photo(img: &image::DynamicImage, ratio: f64) -> image::DynamicImage {
    let width = ((img.width() as f64 * ratio).floor() as u32).max(1);
    let height = ((img.height() as f64 * ratio).floor() as u32).max(1);
    img.resize_exact(width, height, image::imageops::FilterType::Triangle)
}

impl Photo {
    pub fn adjusted(&self) -> bool {
        self.source_bytes > PHOTO_BYTES_LIMIT || self.original_dimensions != self.sent_dimensions
    }
    pub fn description(&self) -> String {
        format!(
            "{} · {:.1} MB → {:.1} MB · {} × {}",
            self.name,
            self.source_bytes as f64 / (1024. * 1024.),
            self.png.len() as f64 / (1024. * 1024.),
            self.sent_dimensions.0,
            self.sent_dimensions.1,
        )
    }
    pub fn load(path: &Path) -> Result<Self> {
        use image::ImageDecoder;
        let size = std::fs::metadata(path).map_err(|e| e.to_string())?.len();
        if size > PHOTO_INPUT_LIMIT as u64 {
            return Err("원본 사진은 128 MB까지 불러올 수 있습니다.".into());
        }
        use std::io::Read;
        let mut bytes = Vec::new();
        std::fs::File::open(path)
            .map_err(|e| e.to_string())?
            .take(PHOTO_INPUT_LIMIT as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        if bytes.len() > PHOTO_INPUT_LIMIT {
            return Err("원본 사진은 128 MB까지 불러올 수 있습니다.".into());
        }
        let mut reader = image::ImageReader::new(std::io::Cursor::new(&bytes))
            .with_guessed_format()
            .map_err(|e| e.to_string())?;
        if !matches!(
            reader.format(),
            Some(
                image::ImageFormat::Png
                    | image::ImageFormat::Jpeg
                    | image::ImageFormat::WebP
                    | image::ImageFormat::Bmp
            )
        ) {
            return Err("JPG·PNG·WEBP·BMP 사진만 지원합니다.".into());
        }
        match reader.format() {
            Some(image::ImageFormat::Png) => {
                let decoder = image::codecs::png::PngDecoder::new(std::io::Cursor::new(&bytes))
                    .map_err(|e| e.to_string())?;
                if decoder.is_apng().map_err(|e| e.to_string())? {
                    return Err("움직이는 사진은 지원하지 않습니다.".into());
                }
            }
            Some(image::ImageFormat::WebP) => {
                let decoder = image::codecs::webp::WebPDecoder::new(std::io::Cursor::new(&bytes))
                    .map_err(|e| e.to_string())?;
                if decoder.has_animation() {
                    return Err("움직이는 사진은 지원하지 않습니다.".into());
                }
            }
            _ => {}
        }
        let mut limits = image::Limits::default();
        limits.max_alloc = Some(384 * 1024 * 1024);
        reader.limits(limits);
        let mut decoder = reader.into_decoder().map_err(|e| e.to_string())?;
        let (w, h) = decoder.dimensions();
        if w == 0 || h == 0 || u64::from(w) * u64::from(h) > PHOTO_DECODE_PIXELS {
            return Err("원본 사진은 6,400만 화소까지 불러올 수 있습니다.".into());
        }
        if decoder.total_bytes() > 384 * 1024 * 1024 {
            return Err("사진을 펼친 크기가 메모리 처리 한도를 초과합니다.".into());
        }
        let orientation = decoder.orientation().map_err(|e| e.to_string())?;
        let mut img = image::DynamicImage::from_decoder(decoder).map_err(|e| e.to_string())?;
        img.apply_orientation(orientation);
        let original_dimensions = (img.width(), img.height());
        let (img, png) = fit_photo(img, PHOTO_BYTES_LIMIT, PHOTO_WORKING_PIXELS)?;
        let sent_dimensions = (img.width(), img.height());
        let small = img
            .thumbnail(480.min(img.width()), 320.min(img.height()))
            .to_rgba8();
        Ok(Self {
            name: path
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .into(),
            hash: digest(&png),
            png: Arc::new(png),
            width: small.width(),
            height: small.height(),
            rgba: Arc::new(small.into_raw()),
            source_bytes: bytes.len(),
            original_dimensions,
            sent_dimensions,
        })
    }
}
#[derive(Clone)]
pub struct Plan {
    pub pid: i32,
    pub rooms: Vec<Room>,
    pub message: String,
    pub photos: Vec<Photo>,
    pub live: bool,
    pub interval: f64,
}
impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.rooms.is_empty() {
            return Err("대화방을 선택하세요.".into());
        }
        if self.message.trim().is_empty() && self.photos.is_empty() {
            return Err("글 또는 사진을 추가하세요.".into());
        }
        if self.message.chars().count() > 10000 {
            return Err("메시지는 10,000자까지 지원합니다.".into());
        }
        if !self.interval.is_finite() || !(0.0..=3600.0).contains(&self.interval) {
            return Err("전송 간격이 올바르지 않습니다.".into());
        }
        let mut keys = HashSet::new();
        if self
            .rooms
            .iter()
            .any(|r| !r.selectable || !keys.insert(&r.key))
        {
            return Err("선택할 수 없거나 중복된 대상입니다.".into());
        }
        validate_photos(&self.photos)
    }
    pub fn scope(&self) -> String {
        format!("darwin:conversations:{}", self.pid)
    }
}
pub fn validate_photos(photos: &[Photo]) -> Result<()> {
    let mut hashes = HashSet::new();
    if photos.iter().any(|p| p.png.len() > PHOTO_BYTES_LIMIT) {
        return Err("전송용 사진은 한 장당 20 MB 이하여야 합니다.".into());
    }
    if photos.len() > 10 || photos.iter().map(|p| p.png.len()).sum::<usize>() > 60 * 1024 * 1024 {
        return Err("사진은 최대 10장·총 60 MB입니다.".into());
    }
    if photos.iter().any(|p| !hashes.insert(&p.hash)) {
        return Err("같은 사진이 중복으로 선택됐습니다.".into());
    }
    Ok(())
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Outcome {
    pub room: Room,
    pub state: String,
    pub detail: String,
}
pub trait Backend {
    fn validate_selection(&self, _rooms: &[Room]) -> Result<()> {
        Ok(())
    }
    fn journal_key(&self, room: &Room) -> Result<String> {
        Ok(room.key.clone())
    }
    fn prepare(&mut self, room: &Room, stop: &Stop) -> Result<()>;
    fn text(&mut self, room: &Room, text: &str, stop: &Stop) -> Result<()>;
    fn photo(&mut self, room: &Room, photo: &Photo, stop: &Stop) -> Result<()>;
    fn finish(&mut self, room: &Room, stop: &Stop) -> Result<()>;
}
pub fn data_dir() -> PathBuf {
    #[cfg(target_os = "macos")]
    let root = PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
        .join("Library/Application Support");
    #[cfg(not(target_os = "macos"))]
    let root = PathBuf::from(
        std::env::var_os("LOCALAPPDATA")
            .or_else(|| std::env::var_os("HOME"))
            .unwrap_or_default(),
    );
    root.join("KakaoFriendSender")
}
pub struct Journal(rusqlite::Connection);
impl Journal {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let c = rusqlite::Connection::open(path).map_err(|e| e.to_string())?;
        c.busy_timeout(Duration::from_secs(5))
            .map_err(|e| e.to_string())?;
        c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS attempts(identity TEXT PRIMARY KEY,state TEXT NOT NULL,updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);").map_err(|e|e.to_string())?;
        Ok(Self(c))
    }
    pub fn identity(scope: &str, key: &str, message: &str, photo: Option<&str>) -> String {
        // Python json.dumps(ensure_ascii=False) compatibility, including spaces.
        let parts = match photo {
            Some(hash) => vec![scope, key, "photo-v1", hash],
            None => vec![scope, key, message],
        };
        digest(format!(
            "[{}]",
            parts
                .iter()
                .map(|s| serde_json::to_string(s).unwrap())
                .collect::<Vec<_>>()
                .join(", ")
        ))
    }
    pub fn reserve(&self, id: &str) -> Result<bool> {
        self.0
            .execute(
                "INSERT OR IGNORE INTO attempts(identity,state) VALUES (?1,'pending')",
                [id],
            )
            .map(|n| n == 1)
            .map_err(|e| e.to_string())
    }
    pub fn state(&self, id: &str) -> Option<String> {
        self.0
            .query_row("SELECT state FROM attempts WHERE identity=?1", [id], |r| {
                r.get(0)
            })
            .ok()
    }
    pub fn finish(&self, id: &str, state: &str) -> Result<()> {
        self.0
            .execute(
                "UPDATE attempts SET state=?1,updated=CURRENT_TIMESTAMP WHERE identity=?2",
                [state, id],
            )
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
    pub fn release(&self, id: &str) -> Result<()> {
        self.0
            .execute(
                "DELETE FROM attempts WHERE identity=?1 AND state='pending'",
                [id],
            )
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
}
pub fn execute(
    plan: &Plan,
    backend: &mut dyn Backend,
    journal: &Journal,
    stop: &Stop,
    mut report: impl FnMut(Outcome),
) -> Result<()> {
    plan.validate()?;
    for (i, room) in plan.rooms.iter().enumerate() {
        check(stop)?;
        let mut sent = 0;
        let mut skipped = 0;
        let mut confirmed = true;
        let result = (|| -> Result<()> {
            if !plan.live {
                backend.prepare(room, stop)?;
                return Ok(());
            }
            let parts = (!plan.message.trim().is_empty())
                .then_some(None)
                .into_iter()
                .chain(plan.photos.iter().map(Some));
            for photo in parts {
                check(stop)?;
                let id = Journal::identity(
                    &plan.scope(),
                    &backend.journal_key(room)?,
                    &plan.message,
                    photo.map(|p| p.hash.as_str()),
                );
                if !journal.reserve(&id)? {
                    skipped += 1;
                    confirmed &= journal.state(&id).as_deref() == Some("submitted");
                    continue;
                }
                if let Err(e) = backend.prepare(room, stop).and_then(|_| check(stop)) {
                    journal.release(&id)?;
                    return Err(e);
                }
                // Once entering an effectful send, every error is uncertain.
                let effect = match photo {
                    Some(p) => backend.photo(room, p, stop),
                    None => backend.text(room, &plan.message, stop),
                };
                if let Err(e) = effect {
                    journal.finish(&id, "uncertain")?;
                    return Err(format!("결과 미확정 · 자동 재전송하지 않습니다: {e}"));
                }
                journal.finish(&id, "submitted")?;
                sent += 1;
            }
            if sent > 0 && confirmed {
                if let Err(e) = backend.finish(room, stop) {
                    return Err(format!("전송 {sent}건 완료 · 창 닫기 중단: {e}"));
                }
            }
            Ok(())
        })();
        let state = if result.is_err() {
            "중단"
        } else if !plan.live {
            "확인 완료"
        } else if sent > 0 {
            "전송 완료"
        } else {
            "중복 건너뜀"
        };
        let detail = match &result {
            Ok(()) => {
                if plan.live {
                    format!("전송 {sent}건 · 기존 이력 {skipped}건")
                } else {
                    "대상 확인 완료 · 입력/전송하지 않았습니다.".into()
                }
            }
            Err(e) => e.clone(),
        };
        report(Outcome {
            room: room.clone(),
            state: state.into(),
            detail,
        });
        result?;
        if i + 1 < plan.rooms.len() {
            wait(stop, Duration::from_secs_f64(plan.interval))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod photo_resize_tests {
    use super::*;
    use image::{DynamicImage, Rgba, RgbaImage};

    #[test]
    fn small_photo_preserves_encoded_bytes_dimensions_and_alpha() {
        let image = DynamicImage::ImageRgba8(RgbaImage::from_pixel(80, 40, Rgba([10, 20, 30, 60])));
        let mut original = std::io::Cursor::new(Vec::new());
        image
            .write_to(&mut original, image::ImageFormat::Png)
            .unwrap();
        let (fitted, bytes) = fit_photo(image, PHOTO_BYTES_LIMIT, PHOTO_WORKING_PIXELS).unwrap();
        assert_eq!((fitted.width(), fitted.height()), (80, 40));
        assert_eq!(bytes, original.into_inner());
        assert_eq!(fitted.to_rgba8().get_pixel(0, 0).0, [10, 20, 30, 60]);
    }

    #[test]
    fn oversized_encoded_photo_shrinks_deterministically_and_keeps_aspect_ratio() {
        let mut random = 1234567_u32;
        let pixels = RgbaImage::from_fn(400, 200, |_, _| {
            let mut rgba = [0; 4];
            for c in &mut rgba {
                random ^= random << 13;
                random ^= random >> 17;
                random ^= random << 5;
                *c = random as u8;
            }
            Rgba(rgba)
        });
        let image = DynamicImage::ImageRgba8(pixels);
        let (fitted, bytes) = fit_photo(image.clone(), 16 * 1024, PHOTO_WORKING_PIXELS).unwrap();
        assert!(bytes.len() <= 16 * 1024);
        assert!(fitted.width() < 400 && fitted.height() < 200);
        assert!((fitted.width() as f64 / fitted.height() as f64 - 2.).abs() < 0.05);
        assert!(fitted.color().has_alpha());
        assert_eq!(
            fit_photo(image, 16 * 1024, PHOTO_WORKING_PIXELS).unwrap().1,
            bytes
        );
    }

    #[test]
    fn working_pixel_cap_handles_regular_and_extremely_thin_photos() {
        for (w, h) in [(400, 200), (1, 4000), (4000, 1)] {
            let image = DynamicImage::ImageRgba8(RgbaImage::from_pixel(w, h, Rgba([1, 2, 3, 255])));
            let (fitted, _) = fit_photo(image, PHOTO_BYTES_LIMIT, 1000).unwrap();
            assert!(u64::from(fitted.width()) * u64::from(fitted.height()) <= 1000);
            assert!(fitted.width() > 0 && fitted.height() > 0);
        }
    }

    #[test]
    fn impossibly_small_limit_returns_error_instead_of_looping() {
        let image = DynamicImage::ImageRgba8(RgbaImage::from_pixel(4, 4, Rgba([0, 0, 0, 0])));
        assert!(fit_photo(image, 1, 1000).is_err());
    }

    #[test]
    fn real_file_over_twenty_mb_is_accepted_without_modifying_original() {
        let path = std::env::temp_dir().join(format!("kakao-oversized-{}.bmp", std::process::id()));
        let image = DynamicImage::ImageRgb8(image::RgbImage::from_pixel(
            3000,
            2500,
            image::Rgb([120, 180, 220]),
        ));
        image
            .save_with_format(&path, image::ImageFormat::Bmp)
            .unwrap();
        let before = std::fs::read(&path).unwrap();
        assert!(before.len() > PHOTO_BYTES_LIMIT);
        let photo = Photo::load(&path).unwrap();
        assert!(photo.png.len() <= PHOTO_BYTES_LIMIT);
        assert!(photo.adjusted());
        assert_eq!(photo.source_bytes, before.len());
        assert_eq!(std::fs::read(&path).unwrap(), before);
        assert_eq!(photo.hash, digest(&*photo.png));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn input_file_above_memory_guard_is_rejected_before_reading() {
        let path =
            std::env::temp_dir().join(format!("kakao-input-limit-{}.png", std::process::id()));
        let file = std::fs::File::create(&path).unwrap();
        file.set_len(PHOTO_INPUT_LIMIT as u64 + 1).unwrap();
        assert!(Photo::load(&path).err().unwrap().contains("128 MB"));
        std::fs::remove_file(path).unwrap();
    }
}
