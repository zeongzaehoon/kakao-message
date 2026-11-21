use crate::core::{canonical, Catalog, Result, Room};

fn self_room(catalog: &Catalog, account: &str) -> Result<Room> {
    let account = canonical(account);
    if account.is_empty() || !catalog.complete {
        return Err("본인 이름과 완전한 채팅 목록이 필요합니다.".into());
    }
    let label = format!("나와의 채팅, {account}");
    let mut matches = catalog.rooms.iter().filter(|room| room.name == label);
    let room = matches.next().ok_or("지정한 본인 방을 찾지 못했습니다.")?;
    if matches.next().is_some() || !room.selectable {
        return Err("본인 방을 유일하게 확인하지 못했습니다.".into());
    }
    Ok(room.clone())
}

#[cfg(target_os = "macos")]
pub fn run(account: &str) -> Result<serde_json::Value> {
    use crate::{core::*, native::Native};
    let stop = Stop::default();
    let mut native = Native::connect(None)?;
    let catalog = native.list(&stop, |_, _| {})?;
    let room = self_room(&catalog, account)?;
    native.validate_selection(std::slice::from_ref(&room))?;
    let photo = test_photo()?;
    let plan = Plan {
        pid: catalog.pid,
        rooms: vec![room],
        message: "Kakao Friend Sender 본인 전송 테스트: 글·사진 전송과 창 닫기를 확인합니다."
            .into(),
        photos: vec![photo],
        live: true,
        interval: 0.,
    };
    plan.validate()?;
    let journal = Journal::open(&data_dir().join("attempts.sqlite3"))?;
    let mut outcomes = Vec::new();
    let result = execute(&plan, &mut native, &journal, &stop, |outcome| {
        // Avoid storing account names and routing keys in the report.
        outcomes.push(serde_json::json!({"state":outcome.state,"detail":outcome.detail}));
    });
    let verified = result.is_ok() && outcomes.len() == 1 && outcomes[0]["state"] == "전송 완료";
    Ok(serde_json::json!({
        "ok":verified,"version":env!("CARGO_PKG_VERSION"),"test_started":true,
        "target":"self_chat_only","text_and_photo_and_close_confirmed":verified,
        "outcomes":outcomes,"error":result.err(),"automatic_retry":false
    }))
}

#[cfg(target_os = "macos")]
fn test_photo() -> Result<crate::core::Photo> {
    use crate::core::{digest, Photo};
    use std::time::{SystemTime, UNIX_EPOCH};
    let nonce = format!(
        "{}:{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    );
    let directory = std::env::temp_dir().join(format!("kakao-self-check-{}", digest(nonce)));
    std::fs::create_dir(&directory).map_err(|e| e.to_string())?;
    let result = (|| {
        let path = directory.join("본인 전송 테스트.png");
        let image = image::RgbaImage::from_fn(640, 360, |x, y| {
            if (250..390).contains(&x) && (120..240).contains(&y) {
                image::Rgba([40u8, 40, 40, 255])
            } else {
                image::Rgba([255u8, 225, 0, 255])
            }
        });
        image.save(&path).map_err(|e| e.to_string())?;
        Photo::load(&path)
    })();
    let cleanup = std::fs::remove_dir_all(&directory).map_err(|e| e.to_string());
    let photo = result?;
    cleanup?;
    Ok(photo)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn catalog(names: &[&str]) -> Catalog {
        Catalog {
            pid: 1,
            complete: true,
            note: String::new(),
            rooms: names
                .iter()
                .enumerate()
                .map(|(i, name)| Room {
                    key: i.to_string(),
                    name: (*name).into(),
                    selectable: true,
                    note: String::new(),
                })
                .collect(),
        }
    }
    #[test]
    fn only_exact_decorated_self_label_can_be_selected() {
        let rooms = catalog(&["본인", "나와의 채팅, 다른 사람", "나와의 채팅, 본인"]);
        assert_eq!(self_room(&rooms, "본인").unwrap().key, "2");
        assert!(self_room(&catalog(&["본인"]), "본인").is_err());
        assert!(self_room(&rooms, "").is_err());
    }
    #[test]
    fn ambiguous_or_disabled_self_chat_never_starts() {
        assert!(self_room(
            &catalog(&["나와의 채팅, 본인", "나와의 채팅, 본인"]),
            "본인"
        )
        .is_err());
        let mut rooms = catalog(&["나와의 채팅, 본인"]);
        rooms.rooms[0].selectable = false;
        assert!(self_room(&rooms, "본인").is_err());
        rooms.rooms[0].selectable = true;
        rooms.complete = false;
        assert!(self_room(&rooms, "본인").is_err());
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn test_image_is_deterministic_for_duplicate_protection() {
        let first = super::test_photo().unwrap();
        let second = super::test_photo().unwrap();
        assert_eq!(first.hash, second.hash);
        assert_eq!(first.sent_dimensions, (640, 360));
        assert!(first.png.len() < 20 * 1024 * 1024);
    }
}
