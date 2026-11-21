use crate::{
    ax::{self, Cf, Node},
    core::*,
    session::CatalogBackend,
    targets::{Observation, Targets},
};
use objc2::{rc::Retained, runtime::ProtocolObject, AnyThread};
use objc2_app_kit::{
    NSApplicationActivationOptions, NSImage, NSPasteboard, NSPasteboardItem, NSPasteboardWriting,
    NSRunningApplication, NSWorkspace,
};
use objc2_foundation::{NSArray, NSData, NSString};
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};

pub struct Native {
    pub pid: i32,
    app: Retained<NSRunningApplication>,
    root: Cf,
    main: Option<Node>,
    table: Option<Node>,
    rows: Targets<Cf>,
    chats: HashMap<String, Node>,
    profile: serde_json::Value,
}
impl Native {
    pub fn connect(expected: Option<i32>) -> Result<Self> {
        if !unsafe { ax::AXIsProcessTrusted() } {
            return Err(
                "시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용에서 이 앱을 허용하세요.".into(),
            );
        }
        let apps = NSWorkspace::sharedWorkspace().runningApplications();
        let apps: Vec<_> = apps
            .iter()
            .filter(|a| {
                a.bundleIdentifier()
                    .is_some_and(|s| s.to_string() == "com.kakao.KakaoTalkMac")
            })
            .collect();
        if apps.len() != 1 {
            return Err("카카오톡을 하나만 실행하고 로그인하세요.".into());
        }
        let app = apps[0].clone();
        let pid = app.processIdentifier();
        if expected.is_some_and(|p| p != pid) {
            return Err("카카오톡이 다시 실행됐습니다. 목록을 새로고침하세요.".into());
        }
        let profile = std::fs::read(data_dir().join("profile-darwin.json"))
            .ok()
            .and_then(|v| serde_json::from_slice(&v).ok())
            .unwrap_or_default();
        Ok(Self {
            pid,
            app,
            root: Cf::app(pid)?,
            main: None,
            table: None,
            rows: Targets::new(),
            chats: HashMap::new(),
            profile,
        })
    }
    fn live(&self, stop: &Stop) -> Result<()> {
        check(stop)?;
        if self.app.isTerminated() {
            Err("카카오톡이 종료됐습니다.".into())
        } else {
            Ok(())
        }
    }
    fn windows(&self) -> Result<Vec<Node>> {
        let mut refs = Vec::new();
        for name in ["AXWindows", "AXChildren", "AXChildrenInNavigationOrder"] {
            for r in self.root.elements(name)? {
                if !refs.contains(&r) {
                    refs.push(r);
                }
            }
        }
        for name in ["AXMainWindow", "AXFocusedWindow"] {
            if let Some(r) = self.root.attr(name)? {
                if !refs.contains(&r) {
                    refs.push(r);
                }
            }
        }
        refs.into_iter().map(Node::read).collect()
    }
    fn catalog_table(&mut self, stop: &Stop) -> Result<(Node, Node)> {
        self.live(stop)?;
        let mains: Vec<_> = self
            .windows()?
            .into_iter()
            .filter(|n| n.role == "AXWindow" && n.id == "Main Window")
            .collect();
        let main = if mains.len() == 1 {
            mains[0].clone()
        } else if mains.is_empty() {
            let old = self
                .main
                .as_ref()
                .ok_or("카카오톡 메인 채팅 탭을 열어 주세요.")?;
            let fresh = Node::read(old.ax.clone())?;
            if fresh.role != "AXWindow" || fresh.id != "Main Window" {
                return Err("카카오톡 메인 채팅 탭을 열어 주세요.".into());
            }
            fresh
        } else {
            return Err("메인 창이 여러 개입니다.".into());
        };
        let area = main.direct("AXScrollArea", "_NS:101", "")?;
        let table = area.direct("AXTable", "_NS:63", "")?;
        self.main = Some(main.clone());
        Ok((main, table))
    }
    fn title_element(row: &Node) -> Result<Node> {
        let mut found = Vec::new();
        for child in row.children()? {
            if child.role == "AXStaticText" && child.id == "_NS:40" {
                found.push(child);
            } else if child.role == "AXCell" {
                for text in child.children()? {
                    if text.role == "AXStaticText" && text.id == "_NS:40" {
                        found.push(text);
                    }
                }
            }
        }
        if found.len() != 1 || found[0].name.is_empty() {
            return Err("채팅 행의 제목을 확인하지 못했습니다.".into());
        }
        Ok(found.remove(0))
    }
    fn title(row: &Node) -> Result<String> {
        Ok(Self::title_element(row)?.name)
    }
    pub fn list(&mut self, stop: &Stop, mut progress: impl FnMut(usize, usize)) -> Result<Catalog> {
        let (_, table) = self.catalog_table(stop)?;
        let total = table.ax.count("AXRows")?;
        let mut refs = Vec::new();
        let mut complete = true;
        if let Some(n) = total {
            for start in (0..n).step_by(256) {
                self.live(stop)?;
                let page = table.ax.page("AXRows", start, 256.min(n - start))?;
                if page.len() != 256.min(n - start) {
                    complete = false;
                }
                refs.extend(page);
            }
        } else {
            refs = table.ax.elements("AXChildren")?;
            complete = false;
        }
        let mut rows = Vec::with_capacity(refs.len());
        let len = refs.len();
        for (i, ax) in refs.into_iter().enumerate() {
            self.live(stop)?;
            let row = Node {
                ax,
                role: "AXRow".into(),
                name: String::new(),
                id: String::new(),
            };
            let name = Self::title(&row)?;
            rows.push((row, name));
            if i % 128 == 0 {
                progress(i, len);
            }
        }
        if let Some(n) = total {
            complete &= table.ax.count("AXRows")? == Some(n);
            if let Some(c) = table.ax.attr("AXRowCount")?.and_then(|v| v.number()) {
                complete &= c == n as i64;
            }
        }
        let writable = table.ax.writable("AXSelectedRows") && table.ax.writable("AXFocused");
        let observations = rows
            .into_iter()
            .map(|(row, name)| Observation {
                hash: row.ax.hash(),
                openable: writable || row.ax.can_press(),
                handle: row.ax,
                name,
            })
            .collect();
        let rooms = self.rows.replace(self.pid, observations, complete);
        self.chats.clear();
        self.table = Some(table);
        progress(len, len);
        Ok(Catalog {
            pid: self.pid,
            rooms,
            complete,
            note: if complete {
                "접근성에 노출된 채팅 목록입니다. 새 방은 새로고침하세요."
            } else {
                "일부 목록만 확인됐습니다. 메인 채팅 탭에서 새로고침하세요."
            }
            .into(),
        })
    }
    fn valid_row(&self, table: &Node, row: &Node, name: &str) -> bool {
        if row.ax.label("AXRole") != "AXRow" {
            return false;
        }
        let belongs = match row.ax.attr("AXParent") {
            Ok(Some(p)) => p == table.ax,
            Ok(None) => table
                .ax
                .elements("AXRows")
                .is_ok_and(|v| v.contains(&row.ax)),
            Err(_) => false,
        };
        belongs && Self::title(row).is_ok_and(|v| v == name)
    }
    /// Read only: enumerate candidate ID fields without exposing names or values.
    pub fn identity_probe(&mut self) -> Result<serde_json::Value> {
        let structure: Vec<_> = self.windows()?.iter().take(12).map(|window| {
            let children = window.children().map(|children| children.into_iter().map(|n| serde_json::json!({"role":n.role,"identifier":n.id})).collect::<Vec<_>>());
            let editor = window.direct("AXScrollArea", "_NS:47", "").and_then(|area| area.direct("AXTextArea", "_NS:51", ""));
            let button = window.direct("AXButton", "", "전송");
            let value = editor.as_ref().ok().and_then(|e| Self::value(e).ok());
            serde_json::json!({"role":window.role,"identifier":window.id,"children":children.ok(),"editor_found":editor.is_ok(),"editor_value_readable":value.is_some(),"editor_empty":value.as_ref().map(|v| v.is_empty()),"send_button_found":button.is_ok(),"send_button_pressable":button.as_ref().is_ok_and(|b| b.ax.can_press()),"send_button_enabled":button.as_ref().is_ok_and(|b| b.enabled()),"chat_structure_valid":self.window_controls(window).is_ok()})
        }).collect();
        let mut report = match self.identity_catalog() {
            Ok(report) => report,
            Err(error) => serde_json::json!({"ok":false,"error":error,"input":0,"sent":0}),
        };
        report["window_structure"] = serde_json::json!(structure);
        Ok(report)
    }
    fn identity_catalog(&mut self) -> Result<serde_json::Value> {
        use std::collections::{BTreeMap, BTreeSet};
        let (_, table) = self.catalog_table(&Stop::default())?;
        let count = table
            .ax
            .count("AXRows")?
            .ok_or("목록 크기를 읽을 수 없습니다.")?;
        let sample = table.ax.page("AXRows", 0, count.min(64))?;
        let mut names = BTreeSet::new();
        let mut stats: BTreeMap<String, (usize, usize, BTreeSet<String>)> = BTreeMap::new();
        let mut decorated_self_labels = 0;
        let mut open_self_windows_matched = 0;
        let windows = self.windows()?;
        for row in &sample {
            let node = Node {
                ax: row.clone(),
                role: "AXRow".into(),
                name: String::new(),
                id: String::new(),
            };
            if let Ok(label) = Self::title(&node) {
                if label.starts_with("나와의 채팅, ") {
                    decorated_self_labels += 1;
                    open_self_windows_matched += windows
                        .iter()
                        .filter(|w| {
                            crate::targets::title_matches(&label, &w.name)
                                && self.window_controls(w).is_ok()
                        })
                        .count();
                }
            }
            let mut objects = vec![("row", row.clone())];
            for child in row.elements("AXChildren")?.into_iter().take(8) {
                if child.label("AXRole") == "AXCell" {
                    objects.push(("cell", child));
                }
            }
            for (scope, object) in objects {
                for attribute in object.attribute_names()? {
                    names.insert(format!("{scope}:{attribute}"));
                    if !(attribute.to_lowercase().contains("identifier")
                        || attribute.ends_with("ID")
                        || ["AXURL", "AXDocument", "AXValue"].contains(&attribute.as_str()))
                    {
                        continue;
                    }
                    let entry = stats.entry(format!("{scope}:{attribute}")).or_default();
                    entry.0 += 1;
                    if let Some(value) = object
                        .attr(&attribute)?
                        .and_then(|v| v.identifier_value())
                        .filter(|v| !v.is_empty())
                    {
                        entry.1 += 1;
                        entry.2.insert(digest(value));
                    }
                }
            }
        }
        let fields: Vec<_> = stats.into_iter().map(|(field, (present, nonempty, values))| serde_json::json!({"field":field,"present":present,"nonempty":nonempty,"distinct":values.len()})).collect();
        Ok(
            serde_json::json!({"ok":true,"rows":count,"sampled_rows":sample.len(),"attributes":names,"fields":fields,"decorated_self_labels":decorated_self_labels,"open_self_windows_matched":open_self_windows_matched,"persistent_room_id_verified":false,"input":0,"sent":0}),
        )
    }
    fn activate(&self, window: &Node, stop: &Stop) -> Result<()> {
        self.live(stop)?;
        #[allow(deprecated)]
        let activated = self
            .app
            .activateWithOptions(NSApplicationActivationOptions::ActivateIgnoringOtherApps);
        // AppKit activation is a request, not proof of foreground ownership.
        // AX reads below are synchronous and do not depend on our main run loop.
        if self.root.writable("AXFrontmost") {
            let _ = self.root.set_true("AXFrontmost");
        }
        let raised = window.ax.action("AXRaise");
        if window.ax.writable("AXMain") {
            let _ = window.ax.set_true("AXMain");
        }
        if self.root.writable("AXFocusedWindow") {
            let _ = self.root.set("AXFocusedWindow", &window.ax);
        }
        if window.ax.writable("AXFocused") {
            let _ = window.ax.focus();
        }
        self.until(
            stop,
            Duration::from_secs(2),
            || Ok(self.focused_window(window) && self.frontmost()),
            "창 포커스를 확인하지 못했습니다.",
        ).map_err(|error| format!("{error} (창={}, 활성요청={activated}, AXFrontmost={}, 대상창포커스={}, AXRaise={})", window.id, self.frontmost(), self.focused_window(window), raised.err().unwrap_or_else(|| "성공".into())))
    }
    fn frontmost(&self) -> bool {
        self.root
            .attr("AXFrontmost")
            .ok()
            .flatten()
            .and_then(|value| value.boolean())
            == Some(true)
    }
    fn focused_window(&self, w: &Node) -> bool {
        self.root
            .attr("AXFocusedWindow")
            .ok()
            .flatten()
            .is_some_and(|a| a == w.ax)
    }
    fn focused_editor(&self, w: &Node, e: &Node) -> bool {
        self.frontmost()
            && self.focused_window(w)
            && self
                .root
                .attr("AXFocusedUIElement")
                .ok()
                .flatten()
                .is_some_and(|a| a == e.ax)
    }
    fn until(
        &self,
        stop: &Stop,
        duration: Duration,
        mut condition: impl FnMut() -> Result<bool>,
        message: &str,
    ) -> Result<()> {
        let start = Instant::now();
        loop {
            self.live(stop)?;
            if condition()? {
                return Ok(());
            }
            if start.elapsed() > duration {
                return Err(message.into());
            }
            wait(stop, Duration::from_millis(40))?;
        }
    }
    fn open(&mut self, room: &Room, stop: &Stop) -> Result<()> {
        self.live(stop)?;
        let (main, table) = self.catalog_table(stop)?;
        let target = self.rows.resolve(room)?;
        let row = Node {
            ax: target.handle.clone(),
            role: "AXRow".into(),
            name: String::new(),
            id: String::new(),
        };
        if !self.valid_row(&table, &row, &room.name) {
            return Err("선택한 방의 화면 객체가 변경되거나 사라졌습니다. 새로고침 후 다시 선택하세요. 이름으로 다른 방을 연결하지 않았습니다.".into());
        }
        self.activate(&main, stop)?;
        if !self.valid_row(&table, &row, &room.name) {
            return Err("열기 직전에 목록이 변경됐습니다.".into());
        }
        if row.ax.can_press() {
            row.ax.action("AXPress")?;
        } else {
            table
                .ax
                .set("AXSelectedRows", &Cf::array(std::slice::from_ref(&row.ax))?)?;
            table.ax.focus()?;
            let verify = || -> Result<bool> {
                let selected = table.ax.elements("AXSelectedRows")?;
                let focus = self.root.attr("AXFocusedUIElement")?;
                Ok(self.frontmost()
                    && self.valid_row(&table, &row, &room.name)
                    && self.focused_window(&main)
                    && selected == vec![row.ax.clone()]
                    && focus.is_some_and(|v| v == table.ax || v == row.ax))
            };
            self.until(
                stop,
                Duration::from_secs(1),
                verify,
                "대상 행 선택과 포커스를 확인하지 못했습니다.",
            )?;
            check(stop)?;
            if !verify()? {
                return Err("열기 직전 포커스가 바뀌었습니다.".into());
            }
            ax::key(36, false)?;
        }
        let started = Instant::now();
        loop {
            self.live(stop)?;
            if let Some(w) = self.root.attr("AXFocusedWindow")? {
                let w = Node::read(w)?;
                if w.ax != main.ax
                    && self.rows.accepts_window_title(room, &w.name)?
                    && self.window_controls(&w).is_ok()
                {
                    self.chats.insert(room.key.clone(), w);
                    return Ok(());
                }
            }
            if started.elapsed() > Duration::from_secs(3) {
                return Err(
                    "선택한 대화창이 열렸는지 확인하지 못했습니다. 입력하지 않았습니다.".into(),
                );
            }
            wait(stop, Duration::from_millis(40))?;
        }
    }
    fn chat(&self, room: &Room, stop: &Stop) -> Result<Node> {
        self.live(stop)?;
        let original = self.chats.get(&room.key).ok_or("대상 확인이 필요합니다.")?;
        let matching: Vec<_> = self
            .windows()?
            .into_iter()
            .filter(|w| w.role == "AXWindow" && w.name == original.name)
            .collect();
        if matching.len() != 1 || matching[0].ax != original.ax {
            return Err("입력 중 대화창이 교체되거나 중복됐습니다.".into());
        }
        let fresh = Node::read(original.ax.clone())?;
        if fresh.name != original.name || fresh.role != "AXWindow" {
            return Err("대화창이 변경됐습니다.".into());
        }
        Ok(fresh)
    }
    fn controls(&self, room: &Room, stop: &Stop) -> Result<(Node, Node, Node)> {
        let chat = self.chat(room, stop)?;
        let (editor, button) = self.window_controls(&chat)?;
        Ok((chat, editor, button))
    }
    fn window_controls(&self, chat: &Node) -> Result<(Node, Node)> {
        if chat.role != "AXWindow" || chat.id == "Main Window" {
            return Err("대화창이 아닌 화면입니다.".into());
        }
        let area = chat.direct("AXScrollArea", "_NS:47", "")?;
        let select = |key: &str, field: &str, default: &str| {
            self.profile
                .get("selectors")
                .and_then(|s| s.get(key))
                .and_then(|s| s.get(field))
                .and_then(|s| s.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or(default)
                .to_owned()
        };
        let editor = area.direct(
            &select("editor", "role", "AXTextArea"),
            &select("editor", "identifier", "_NS:51"),
            "",
        )?;
        let button = chat.direct(
            &select("send_button", "role", "AXButton"),
            &select("send_button", "identifier", ""),
            &select("send_button", "name", "전송"),
        )?;
        Ok((editor, button))
    }
    fn value(editor: &Node) -> Result<String> {
        editor
            .ax
            .attr("AXValue")?
            .and_then(|v| v.text())
            .ok_or_else(|| "입력창 값을 읽을 수 없어 전송을 중단했습니다.".into())
    }
    fn sheets(chat: &Node) -> Result<Vec<Node>> {
        let mut refs = chat.ax.elements("AXSheets")?;
        for child in chat.children()? {
            if child.role == "AXSheet" && !refs.contains(&child.ax) {
                refs.push(child.ax);
            }
        }
        refs.into_iter().map(Node::read).collect()
    }
    fn paste(&self, room: &Room, clipboard: &Clipboard, stop: &Stop) -> Result<()> {
        let (chat, editor, _) = self.controls(room, stop)?;
        self.activate(&chat, stop)?;
        editor.ax.focus()?;
        self.until(
            stop,
            Duration::from_secs(1),
            || Ok(self.focused_editor(&chat, &editor)),
            "입력창 포커스 확인 실패",
        )?;
        clipboard.verify()?;
        self.live(stop)?;
        if !self.focused_editor(&chat, &editor)
            || !Self::value(&editor)?.is_empty()
            || !Self::sheets(&chat)?.is_empty()
        {
            return Err("붙여넣기 직전 대상 또는 초안이 변경됐습니다.".into());
        }
        ax::key(9, true)
    }
    fn press_send(button: &Node) -> Result<()> {
        if !button.enabled() || !button.ax.can_press() {
            return Err("전송 버튼이 비활성 상태입니다.".into());
        }
        let _ = button.ax.action("AXPress");
        Ok(())
    }
}
impl CatalogBackend for Native {
    fn pid(&self) -> i32 {
        self.pid
    }
    fn alive(&self) -> bool {
        !self.app.isTerminated()
    }
    fn catalog(&mut self, stop: &Stop, progress: &mut dyn FnMut(usize, usize)) -> Result<Catalog> {
        self.list(stop, progress)
    }
}
impl Backend for Native {
    fn validate_selection(&self, rooms: &[Room]) -> Result<()> {
        for room in rooms {
            self.rows.resolve(room)?;
        }
        Ok(())
    }
    fn journal_key(&self, room: &Room) -> Result<String> {
        Ok(self.rows.resolve(room)?.legacy_key.clone())
    }

    fn prepare(&mut self, room: &Room, stop: &Stop) -> Result<()> {
        if !room.selectable {
            return Err("선택할 수 없는 대상입니다.".into());
        }
        if self
            .chats
            .get(&room.key)
            .is_some_and(|w| w.ax.label("AXRole") != "AXWindow")
        {
            self.chats.remove(&room.key);
        }
        if !self.chats.contains_key(&room.key) {
            self.open(room, stop)?;
        }
        let (chat, editor, _) = match self.controls(room, stop) {
            Ok(controls) => controls,
            Err(error) => {
                self.chats.remove(&room.key);
                return Err(error);
            }
        };
        if !Self::value(&editor)?.is_empty() || !Self::sheets(&chat)?.is_empty() {
            return Err("대화창에 작성 중인 내용 또는 첨부창이 있습니다.".into());
        }
        Ok(())
    }
    fn text(&mut self, room: &Room, text: &str, stop: &Stop) -> Result<()> {
        let mut clipboard = Clipboard::text(text)?;
        let entered = (|| {
            self.paste(room, &clipboard, stop)?;
            self.until(
                stop,
                Duration::from_secs(3),
                || {
                    clipboard.verify()?;
                    let (_, editor, _) = self.controls(room, stop)?;
                    let value = Self::value(&editor)?.replace("\r\n", "\n");
                    if !value.is_empty() && value != text.replace("\r\n", "\n") {
                        return Err("입력 내용이 원문과 다릅니다.".into());
                    }
                    Ok(value == text.replace("\r\n", "\n"))
                },
                "텍스트 입력 확인 실패",
            )
        })();
        let restored = clipboard.restore();
        entered?;
        restored?;
        self.until(
            stop,
            Duration::from_secs(3),
            || {
                let (_, e, b) = self.controls(room, stop)?;
                if Self::value(&e)?.replace("\r\n", "\n") != text.replace("\r\n", "\n") {
                    return Err("전송 전 내용이 변경됐습니다.".into());
                }
                Ok(b.enabled())
            },
            "전송 버튼 활성화 실패",
        )?;
        let (_, e, b) = self.controls(room, stop)?;
        check(stop)?;
        if Self::value(&e)?.replace("\r\n", "\n") != text.replace("\r\n", "\n") {
            return Err("전송 전 내용이 변경됐습니다.".into());
        }
        Self::press_send(&b)?;
        let verify = Stop::default();
        self.until(
            &verify,
            Duration::from_secs(3),
            || {
                let (_, e, _) = self.controls(room, &verify)?;
                Ok(Self::value(&e)?.is_empty())
            },
            "전송 후 입력창 비움을 확인하지 못했습니다.",
        )
    }
    fn photo(&mut self, room: &Room, photo: &Photo, stop: &Stop) -> Result<()> {
        let mut clipboard = Clipboard::photo(photo)?;
        let result = (|| {
            self.paste(room, &clipboard, stop)?;
            let chat = self.chat(room, stop)?;
            self.until(
                stop,
                Duration::from_secs(4),
                || {
                    clipboard.verify()?;
                    Ok(!Self::sheets(&chat)?.is_empty())
                },
                "사진 확인 창을 확인하지 못했습니다.",
            )?;
            let sheets = Self::sheets(&chat)?;
            if sheets.len() != 1 {
                return Err("사진 확인 창이 여러 개입니다.".into());
            }
            let sheet = sheets[0].clone();
            let mut stack = vec![sheet.clone()];
            let mut buttons = Vec::new();
            let mut images = 0;
            let mut seen = 0;
            while let Some(node) = stack.pop() {
                check(stop)?;
                seen += 1;
                if seen > 5000 {
                    return Err("사진 확인 창 요소가 너무 많습니다.".into());
                }
                if node.role == "AXButton" && ["전송", "Send"].contains(&node.name.as_str()) {
                    buttons.push(node.clone());
                }
                if node.role == "AXImage" {
                    images += 1;
                }
                stack.extend(node.children()?);
            }
            if images == 0 || buttons.len() != 1 {
                return Err("사진 미리보기와 전송 버튼을 확인하지 못했습니다.".into());
            }
            let current = self.chat(room, stop)?;
            let sheets = Self::sheets(&current)?;
            clipboard.verify()?;
            check(stop)?;
            if sheets.len() != 1 || sheets[0].ax != sheet.ax {
                return Err("사진 확인 창이 변경됐습니다.".into());
            }
            Self::press_send(&buttons[0])?;
            let verify = Stop::default();
            self.until(
                &verify,
                Duration::from_secs(4),
                || {
                    let (c, e, _) = self.controls(room, &verify)?;
                    Ok(Self::sheets(&c)?.is_empty() && Self::value(&e)?.is_empty())
                },
                "사진 전송 완료를 확인하지 못했습니다.",
            )
        })();
        let restored = clipboard.restore();
        result.and(restored)
    }
    fn finish(&mut self, room: &Room, stop: &Stop) -> Result<()> {
        let (chat, editor, _) = self.controls(room, stop)?;
        if !Self::value(&editor)?.is_empty() || !Self::sheets(&chat)?.is_empty() {
            return Err("초안이 있어 창을 닫지 않았습니다.".into());
        }
        let close = chat
            .ax
            .attr("AXCloseButton")?
            .ok_or("닫기 버튼이 없습니다.")?;
        if close.attr("AXWindow")?.as_ref() != Some(&chat.ax)
            || close.label("AXSubrole") != "AXCloseButton"
        {
            return Err("닫기 버튼의 창을 확인하지 못했습니다.".into());
        }
        check(stop)?;
        let _ = close.action("AXPress");
        let verify = Stop::default();
        self.until(
            &verify,
            Duration::from_secs(2),
            || {
                let present = self.windows()?.iter().any(|w| w.ax == chat.ax);
                Ok(chat.ax.label("AXRole") != "AXWindow"
                    || (!present
                        && chat
                            .ax
                            .attr("AXVisible")
                            .ok()
                            .flatten()
                            .and_then(|v| v.boolean())
                            == Some(false)))
            },
            "대화창이 닫혔는지 확인하지 못했습니다.",
        )?;
        self.chats.remove(&room.key);
        Ok(())
    }
}
struct Clipboard {
    board: Retained<NSPasteboard>,
    saved: Vec<Retained<NSPasteboardItem>>,
    owned: isize,
    restored: bool,
    _source: Retained<ProtocolObject<dyn NSPasteboardWriting>>,
}
impl Clipboard {
    fn install(source: Retained<ProtocolObject<dyn NSPasteboardWriting>>) -> Result<Self> {
        let board = NSPasteboard::generalPasteboard();
        let before = board.changeCount();
        let mut saved = Vec::new();
        if let Some(items) = board.pasteboardItems() {
            for item in items.iter() {
                let copy = NSPasteboardItem::new();
                for kind in item.types().iter() {
                    let data = item
                        .dataForType(&kind)
                        .ok_or("기존 클립보드를 보관하지 못했습니다.")?;
                    if !copy.setData_forType(&data, &kind) {
                        return Err("기존 클립보드 보관 실패".into());
                    }
                }
                saved.push(copy);
            }
        }
        if board.changeCount() != before {
            return Err("클립보드가 변경됐습니다.".into());
        }
        let owned = board.clearContents();
        let mut guard = Self {
            board,
            saved,
            owned,
            restored: false,
            _source: source,
        };
        if !guard
            .board
            .writeObjects(&NSArray::from_slice(&[guard._source.as_ref()]))
        {
            return Err("클립보드 쓰기 실패".into());
        }
        guard.owned = guard.board.changeCount();
        Ok(guard)
    }
    fn text(text: &str) -> Result<Self> {
        let item = NSPasteboardItem::new();
        if !item.setString_forType(
            &NSString::from_str(text),
            &NSString::from_str("public.utf8-plain-text"),
        ) {
            return Err("문자열 클립보드 준비 실패".into());
        }
        Self::install(ProtocolObject::from_retained(item))
    }
    fn photo(photo: &Photo) -> Result<Self> {
        let data = NSData::with_bytes(&photo.png);
        let image =
            NSImage::initWithData(NSImage::alloc(), &data).ok_or("사진을 읽지 못했습니다.")?;
        Self::install(ProtocolObject::from_retained(image))
    }
    fn verify(&self) -> Result<()> {
        if self.board.changeCount() == self.owned {
            Ok(())
        } else {
            Err("사용자가 클립보드를 변경했습니다. 붙여넣기를 중단합니다.".into())
        }
    }
    fn restore(&mut self) -> Result<()> {
        if self.restored {
            return Ok(());
        }
        self.restored = true;
        if self.board.changeCount() == self.owned {
            self.board.clearContents();
            if !self.saved.is_empty() {
                let refs: Vec<&ProtocolObject<dyn NSPasteboardWriting>> = self
                    .saved
                    .iter()
                    .map(|p| ProtocolObject::from_ref::<NSPasteboardItem>(p))
                    .collect();
                if !self.board.writeObjects(&NSArray::from_slice(&refs)) {
                    return Err("기존 클립보드 복원 실패".into());
                }
            }
        }
        Ok(())
    }
}
impl Drop for Clipboard {
    fn drop(&mut self) {
        let _ = self.restore();
    }
}
