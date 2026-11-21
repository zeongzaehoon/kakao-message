//! Session-local bindings to retained accessibility objects, never name-based routing.
use crate::core::{digest, Result, Room};
use std::{
    collections::{HashMap, HashSet},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

static NEXT_SESSION: AtomicU64 = AtomicU64::new(1);

/// Presentation variant only; never use this to look up or rebind a room.
pub fn title_matches(label: &str, title: &str) -> bool {
    !title.is_empty() && (label == title || label.strip_prefix("나와의 채팅, ") == Some(title))
}
pub struct Observation<H> {
    pub handle: H,
    pub hash: usize,
    pub name: String,
    pub openable: bool,
}
pub struct Target<H> {
    pub handle: H,
    pub room: Room,
    // Existing journal identities stay compatible; this is not a routing key.
    pub legacy_key: String,
    hash: usize,
}
pub struct Targets<H> {
    session: String,
    sequence: u64,
    entries: HashMap<String, Target<H>>,
    window_titles: HashMap<String, usize>,
}
impl<H: PartialEq> Targets<H> {
    pub fn new() -> Self {
        Self {
            session: digest(format!(
                "{}:{}:{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos(),
                NEXT_SESSION.fetch_add(1, Ordering::Relaxed)
            )),
            sequence: 0,
            entries: HashMap::new(),
            window_titles: HashMap::new(),
        }
    }
    pub fn resolve(&self, room: &Room) -> Result<&Target<H>> {
        let target = self.entries.get(&room.key).ok_or("선택한 방의 연결이 만료됐습니다. 목록을 새로고침하고 다시 선택하세요. 이름으로 다른 방을 연결하지 않았습니다.")?;
        if !target.room.selectable || target.room.name != room.name {
            return Err("선택 당시 대화방 정보가 변경됐습니다. 다시 확인하고 선택하세요.".into());
        }
        Ok(target)
    }
    pub fn accepts_window_title(&self, room: &Room, title: &str) -> Result<bool> {
        self.resolve(room)?;
        if !title_matches(&room.name, title) {
            return Ok(false);
        }
        // An alias must not overlap another known room, including disabled rows.
        Ok(self.window_titles.get(title) == Some(&1))
    }
    pub fn replace(&mut self, pid: i32, rows: Vec<Observation<H>>, complete: bool) -> Vec<Room> {
        self.window_titles.clear();
        let mut titles: HashMap<&str, usize> = HashMap::new();
        let mut buckets: HashMap<usize, Vec<usize>> = HashMap::new();
        for (i, row) in rows.iter().enumerate() {
            *self.window_titles.entry(row.name.clone()).or_default() += 1;
            if let Some(alias) = row
                .name
                .strip_prefix("나와의 채팅, ")
                .filter(|s| !s.is_empty())
            {
                *self.window_titles.entry(alias.to_owned()).or_default() += 1;
            }
            *titles.entry(&row.name).or_default() += 1;
            buckets.entry(row.hash).or_default().push(i);
        }
        let unique: Vec<bool> = rows
            .iter()
            .map(|row| {
                titles[row.name.as_str()] == 1
                    && buckets[&row.hash]
                        .iter()
                        .filter(|&&i| rows[i].handle == row.handle)
                        .count()
                        == 1
            })
            .collect();
        let old = std::mem::take(&mut self.entries);
        let mut previous: HashMap<usize, Vec<&Target<H>>> = HashMap::new();
        for target in old.values() {
            previous.entry(target.hash).or_default().push(target);
        }
        let mut reused = HashSet::new();
        rows.into_iter()
            .zip(unique)
            .map(|(row, unique)| {
                let matched = previous.get(&row.hash).and_then(|bucket| {
                    let mut matches = bucket.iter().copied().filter(|target| {
                        target.handle == row.handle && target.room.name == row.name
                    });
                    let first = matches.next()?;
                    (matches.next().is_none() && !reused.contains(&first.room.key)).then_some(first)
                });
                let key = if let Some(target) = matched {
                    reused.insert(target.room.key.clone());
                    target.room.key.clone()
                } else {
                    self.sequence += 1;
                    format!("session:{}:{}", self.session, self.sequence)
                };
                let legacy_key = matched.map(|t| t.legacy_key.clone()).unwrap_or_else(|| {
                    format!(
                        "conversation:{}",
                        digest(format!("{pid}:{}:{}", row.hash, row.name))
                    )
                });
                let room = Room {
                    key: key.clone(),
                    name: row.name,
                    selectable: complete && unique && row.openable,
                    note: if !complete {
                        "부분 목록 · 새로고침 필요"
                    } else if !unique {
                        "동일 이름 또는 중복 객체 · 선택 불가"
                    } else if !row.openable {
                        "행 열기 미지원"
                    } else {
                        ""
                    }
                    .into(),
                };
                self.entries.insert(
                    key,
                    Target {
                        handle: row.handle,
                        room: room.clone(),
                        legacy_key,
                        hash: row.hash,
                    },
                );
                room
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn decorated_self_label_accepts_full_or_plain_title_only() {
        assert!(title_matches("나와의 채팅, 본인", "본인"));
        assert!(title_matches("나와의 채팅, 본인", "나와의 채팅, 본인"));
        assert!(!title_matches("나와의 채팅, 본인", "다른 사람"));
        assert!(!title_matches("나와의 채팅, ", ""));
        assert!(!title_matches("친구, 팀", "팀"));
        assert!(title_matches("친구", "친구"));
    }
    #[test]
    fn self_title_collision_never_resolves_to_another_room() {
        let mut targets = Targets::new();
        let rooms = targets.replace(1, vec![row(1, "나와의 채팅, 본인"), row(2, "본인")], true);
        assert!(!targets.accepts_window_title(&rooms[0], "본인").unwrap());
        assert!(!targets.accepts_window_title(&rooms[1], "본인").unwrap());
        assert!(targets
            .accepts_window_title(&rooms[0], "나와의 채팅, 본인")
            .unwrap());
    }
    #[test]
    fn title_alias_does_not_replace_the_selected_handle() {
        let mut targets = Targets::new();
        let room = targets
            .replace(1, vec![row(11, "나와의 채팅, 본인")], true)
            .remove(0);
        assert!(targets.accepts_window_title(&room, "본인").unwrap());
        assert_eq!(targets.resolve(&room).unwrap().handle, 11);
        targets.replace(1, vec![row(22, "나와의 채팅, 본인")], true);
        assert!(targets.accepts_window_title(&room, "본인").is_err());
    }
    fn row(handle: u64, name: &str) -> Observation<u64> {
        Observation {
            handle,
            hash: handle as usize,
            name: name.into(),
            openable: true,
        }
    }
    #[test]
    fn reorder_keeps_selected_object_and_key() {
        let mut targets = Targets::new();
        let first = targets.replace(1, vec![row(11, "A"), row(22, "B")], true);
        let selected = first[0].clone();
        let next = targets.replace(1, vec![row(22, "B"), row(11, "A")], true);
        assert_eq!(next[1].key, selected.key);
        assert_eq!(targets.resolve(&selected).unwrap().handle, 11);
    }
    #[test]
    fn replacement_with_same_name_does_not_inherit_selection() {
        let mut targets = Targets::new();
        let old = targets.replace(1, vec![row(11, "A")], true).remove(0);
        let new = targets.replace(1, vec![row(22, "A")], true).remove(0);
        assert_ne!(old.key, new.key);
        assert!(targets.resolve(&old).is_err());
    }
    #[test]
    fn reused_row_slot_with_changed_name_is_not_the_selected_room() {
        let mut targets = Targets::new();
        let old = targets.replace(1, vec![row(11, "A")], true).remove(0);
        targets.replace(1, vec![row(11, "B"), row(22, "A")], true);
        assert!(targets.resolve(&old).is_err());
    }
    #[test]
    fn hash_collision_is_not_identity() {
        let mut targets = Targets::new();
        let mut a = row(11, "A");
        a.hash = 7;
        let mut b = row(22, "B");
        b.hash = 7;
        let rooms = targets.replace(1, vec![a, b], true);
        assert!(rooms.iter().all(|r| r.selectable));
        assert_ne!(rooms[0].key, rooms[1].key);
        assert_eq!(targets.resolve(&rooms[0]).unwrap().handle, 11);
        assert_eq!(targets.resolve(&rooms[1]).unwrap().handle, 22);
    }
    #[test]
    fn duplicate_names_and_incomplete_snapshot_are_not_sendable() {
        let mut targets = Targets::new();
        let rooms = targets.replace(1, vec![row(11, "A"), row(22, "A")], true);
        assert!(rooms.iter().all(|r| targets.resolve(r).is_err()));
        let rooms = targets.replace(1, vec![row(11, "A")], false);
        assert!(targets.resolve(&rooms[0]).is_err());
    }
    #[test]
    fn new_connection_never_accepts_old_keys_and_preserves_legacy_journal_identity() {
        let mut first = Targets::new();
        let a = first.replace(1, vec![row(11, "A")], true).remove(0);
        let mut next = Targets::new();
        let b = next.replace(1, vec![row(11, "A")], true).remove(0);
        assert!(next.resolve(&a).is_err());
        assert_eq!(
            first.resolve(&a).unwrap().legacy_key,
            next.resolve(&b).unwrap().legacy_key
        );
    }
    #[test]
    fn ten_thousand_rooms_reordered_keep_keys() {
        let mut targets = Targets::new();
        let first = targets.replace(
            1,
            (0..10000).map(|i| row(i, &format!("room-{i}"))).collect(),
            true,
        );
        let second = targets.replace(
            1,
            (0..10000)
                .rev()
                .map(|i| row(i, &format!("room-{i}")))
                .collect(),
            true,
        );
        for i in [0, 234, 9999] {
            assert_eq!(first[i].key, second[9999 - i].key);
        }
    }
}
