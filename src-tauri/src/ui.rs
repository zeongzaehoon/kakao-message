mod design;
use crate::{
    core::*,
    session::{Event, Worker},
};
use design::*;
use eframe::egui::{self, Color32, RichText, Vec2};
use std::{
    collections::HashSet,
    sync::{atomic::Ordering, mpsc},
    thread,
    time::Duration,
};
pub struct App {
    catalog: Option<Catalog>,
    query: String,
    selected_only: bool,
    search_open: bool,
    focus_search: bool,
    visible: Vec<usize>,
    selected: HashSet<String>,
    message: String,
    photos: Vec<Photo>,
    textures: Vec<egui::TextureHandle>,
    interval: f64,
    live: bool,
    status: String,
    history: bool,
    settings: bool,
    confirm: bool,
    results: Vec<Outcome>,
    tx: mpsc::Sender<Event>,
    rx: mpsc::Receiver<Event>,
    stop: Stop,
    job: Option<thread::JoinHandle<()>>,
    worker: Worker,
    busy: bool,
    progress: (usize, usize),
    close_confirm: bool,
    allow_close: bool,
    close_after_job: bool,
    smoke: Option<std::path::PathBuf>,
    smoke_frames: usize,
}
impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, smoke: Option<std::path::PathBuf>) -> Self {
        let mut fonts = egui::FontDefinitions::default();
        fonts.families.insert(
            egui::FontFamily::Name("semibold".into()),
            fonts.families[&egui::FontFamily::Proportional].clone(),
        );
        for path in [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "C:/Windows/Fonts/malgun.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ] {
            if let Ok(data) = std::fs::read(path) {
                let mut semibold = egui::FontData::from_owned(data.clone());
                if path.ends_with("AppleSDGothicNeo.ttc") {
                    semibold.index = 4;
                }
                fonts
                    .font_data
                    .insert("korean-semibold".into(), semibold.into());
                fonts.families.insert(
                    egui::FontFamily::Name("semibold".into()),
                    vec!["korean-semibold".into()],
                );
                fonts
                    .font_data
                    .insert("korean".into(), egui::FontData::from_owned(data).into());
                fonts
                    .families
                    .get_mut(&egui::FontFamily::Proportional)
                    .unwrap()
                    .insert(0, "korean".into());
                break;
            }
        }
        cc.egui_ctx.set_fonts(fonts);
        design::apply(&cc.egui_ctx);
        let (tx, rx) = mpsc::channel();
        let worker = Worker::new(tx.clone());
        let mut app = Self {
            catalog: None,
            query: String::new(),
            selected_only: false,
            search_open: false,
            focus_search: false,
            visible: vec![],
            selected: HashSet::new(),
            message: String::new(),
            photos: vec![],
            textures: vec![],
            interval: 2.,
            live: false,
            status: "카카오톡 채팅 탭을 열어 주세요.".into(),
            history: false,
            settings: false,
            confirm: false,
            results: vec![],
            tx,
            rx,
            stop: Stop::default(),
            job: None,
            worker,
            busy: false,
            progress: (0, 0),
            close_confirm: false,
            allow_close: false,
            close_after_job: false,
            smoke,
            smoke_frames: 0,
        };
        if app.smoke.is_some() {
            app.catalog = Some(Catalog {
                pid: 0,
                rooms: (0..10000)
                    .map(|i| Room {
                        key: i.to_string(),
                        name: [
                            "나와의 채팅",
                            "프로젝트 팀",
                            "디자인 리뷰",
                            "스터디 모임",
                            "주말 약속",
                            "새로운 아이디어",
                        ]
                        .get(i)
                        .map(|s| s.to_string())
                        .unwrap_or_else(|| format!("테스트 대화방 {i:05}")),
                        selectable: true,
                        note: String::new(),
                    })
                    .collect(),
                complete: true,
                note: String::new(),
            });
            app.filter();
            app.selected.extend(["0".to_string(), "1".to_string()]);
            app.message =
                "안녕하세요.\n공유드릴 내용을 확인해 주세요.\n오늘도 좋은 하루 보내세요!".into();
            app.status = "10,000개 가상 대화방 렌더링 검사".into();
        } else {
            app.load();
        }
        app
    }
    /// Screenshot scenarios use only the synthetic catalog, never KakaoTalk.
    pub fn self_test_view(&mut self, view: &str) {
        if self.smoke.is_none() {
            return;
        }
        match view {
            "history" => {
                self.history = true;
                self.results = self.catalog.as_ref().unwrap().rooms[..2]
                    .iter()
                    .map(|room| Outcome {
                        room: room.clone(),
                        state: "확인 완료".into(),
                        detail: "화면 검사 · 실제 입력하거나 전송하지 않았습니다.".into(),
                    })
                    .collect();
            }
            "settings" => self.settings = true,
            "search" => {
                self.search_open = true;
                self.query = "리뷰".into();
                self.filter();
            }
            "empty" => {
                self.message.clear();
                self.selected.clear();
            }
            "confirm" => self.confirm = true,
            _ => {}
        }
    }
    fn spawn(
        &mut self,
        work: impl FnOnce(mpsc::Sender<Event>, Stop) -> Result<()> + Send + 'static,
    ) {
        if self.busy {
            return;
        }
        self.busy = true;
        self.stop = Stop::default();
        self.progress = (0, 0);
        let tx = self.tx.clone();
        let stop = self.stop.clone();
        self.job = Some(thread::spawn(move || {
            let result=std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                #[cfg(target_os = "macos")]
                {objc2::rc::autoreleasepool(|_|work(tx.clone(),stop))}
                #[cfg(not(target_os = "macos"))]
                {work(tx.clone(),stop)}
            })).unwrap_or_else(|_|Err("작업 중 내부 오류가 발생했습니다. 전송 결과를 확인하세요. 자동 재시도하지 않습니다.".into()));
            let _ = tx.send(Event::Done(result));
        }));
    }
    fn load(&mut self) {
        if self.busy {
            return;
        }
        self.live = false;
        self.status = "채팅 목록을 읽고 있습니다…".into();
        self.busy = true;
        self.stop = Stop::default();
        self.progress = (0, 0);
        if let Err(error) = self.worker.load(self.stop.clone()) {
            self.busy = false;
            self.status = error;
        }
    }

    fn filter(&mut self) {
        let query = self.query.to_lowercase();
        self.visible = self
            .catalog
            .as_ref()
            .map(|c| {
                c.rooms
                    .iter()
                    .enumerate()
                    .filter(|(_, r)| {
                        (!self.selected_only || self.selected.contains(&r.key))
                            && r.name.to_lowercase().contains(&query)
                    })
                    .map(|(i, _)| i)
                    .collect()
            })
            .unwrap_or_default();
    }
    fn plan(&self) -> Result<Plan> {
        let cat = self.catalog.as_ref().ok_or("목록을 먼저 불러오세요.")?;
        if !cat.complete {
            return Err(cat.note.clone());
        }
        let rooms = cat
            .rooms
            .iter()
            .enumerate()
            .filter(|(_, r)| self.selected.contains(&r.key))
            .map(|(_, r)| r.clone())
            .collect();
        let p = Plan {
            pid: cat.pid,
            rooms,
            message: self.message.clone(),
            photos: self.photos.clone(),
            live: self.live,
            interval: self.interval,
        };
        p.validate()?;
        Ok(p)
    }
    fn run(&mut self) {
        let plan = match self.plan() {
            Ok(p) => p,
            Err(e) => {
                self.status = e;
                return;
            }
        };
        self.results.clear();
        self.history = true;
        self.confirm = false;
        self.status = if plan.live {
            "전송 중"
        } else {
            "대상 확인 중"
        }
        .into();
        self.busy = true;
        self.stop = Stop::default();
        if let Err(error) = self.worker.send(plan, self.stop.clone()) {
            self.busy = false;
            self.status = error;
        }
    }

    fn add_photos(&mut self) {
        if let Some(paths) = rfd::FileDialog::new()
            .add_filter("사진", &["jpg", "jpeg", "png", "webp", "bmp"])
            .pick_files()
        {
            let existing = self.photos.clone();
            self.spawn(move |tx, stop| {
                let mut photos = existing;
                for p in paths {
                    check(&stop)?;
                    photos.push(Photo::load(&p)?);
                    validate_photos(&photos)?;
                }
                tx.send(Event::Photos(photos)).map_err(|e| e.to_string())?;
                Ok(())
            });
        }
    }
    fn events(&mut self, ctx: &egui::Context) {
        while let Ok(event) = self.rx.try_recv() {
            match event {
                Event::Catalog(c) => {
                    self.status = c.note.clone();
                    let valid: HashSet<_> = c
                        .rooms
                        .iter()
                        .filter(|r| r.selectable)
                        .map(|r| r.key.clone())
                        .collect();
                    self.selected.retain(|key| valid.contains(key));
                    self.catalog = Some(c);
                    self.filter();
                }
                Event::Invalidated => {
                    self.catalog = None;
                    self.selected.clear();
                    self.filter();
                }
                Event::Progress(i, n) => {
                    self.progress = (i, n);
                    self.status = format!("채팅 목록 조회 {i} / {n}").replace(',', "");
                }
                Event::Outcome(o) => self.results.push(o),
                Event::Photos(p) => {
                    let adjusted = p.iter().filter(|photo| photo.adjusted()).count();
                    self.status = if adjusted > 0 {
                        format!(
                            "사진 {}장 준비 · {}장 용량 자동 조정 (원본 보존)",
                            p.len(),
                            adjusted
                        )
                    } else {
                        format!("사진 {}장 준비", p.len())
                    };
                    self.textures = p
                        .iter()
                        .map(|p| {
                            ctx.load_texture(
                                &p.hash,
                                egui::ColorImage::from_rgba_unmultiplied(
                                    [p.width as usize, p.height as usize],
                                    &p.rgba,
                                ),
                                Default::default(),
                            )
                        })
                        .collect();
                    self.photos = p;
                }
                Event::Done(r) => {
                    self.busy = false;
                    if let Some(job) = self.job.take() {
                        let _ = job.join();
                    }
                    if let Err(e) = r {
                        self.status = e;
                    } else if self.history {
                        self.status = "작업 완료".into();
                    }
                    if self.close_after_job {
                        self.allow_close = true;
                        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                    }
                }
            }
        }
    }
    fn export(&mut self) {
        if let Some(path) = rfd::FileDialog::new()
            .set_file_name("전송결과.csv")
            .save_file()
        {
            let quote = |s: &str| format!("\"{}\"", s.replace('"', "\"\""));
            let mut out = "\u{feff}대화방,상태,내용\n".to_string();
            for r in &self.results {
                out.push_str(&format!(
                    "{},{},{}\n",
                    quote(&r.room.name),
                    quote(&r.state),
                    quote(&r.detail)
                ));
            }
            self.status = match std::fs::write(path, out) {
                Ok(()) => "CSV 저장 완료".into(),
                Err(e) => e.to_string(),
            };
        }
    }
    fn navigation(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("navigation")
            .exact_width(76.)
            .resizable(false)
            .frame(
                egui::Frame::NONE
                    .fill(RAIL)
                    .inner_margin(egui::Margin::symmetric(20, 0)),
            )
            .show(ctx, |ui| {
                ui.add_space(74.);
                if icon_button(
                    ui,
                    Icon::Chat,
                    "메시지 작성",
                    !self.settings && !self.history,
                )
                .clicked()
                {
                    self.settings = false;
                    self.history = false;
                }
                ui.add_space(24.);
                if icon_button(
                    ui,
                    Icon::History,
                    "진행 내역",
                    !self.settings && self.history,
                )
                .clicked()
                {
                    self.settings = false;
                    self.history = true;
                }
                ui.with_layout(egui::Layout::bottom_up(egui::Align::Center), |ui| {
                    ui.add_space(24.);
                    if icon_button(ui, Icon::Settings, "연결 설정", self.settings).clicked() {
                        self.settings = !self.settings;
                    }
                });
            });
    }

    fn rooms_panel(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("rooms")
            .exact_width(360.)
            .resizable(false)
            .frame(
                egui::Frame::NONE
                    .fill(LIST)
                    .inner_margin(egui::Margin::symmetric(16, 0)),
            )
            .show(ctx, |ui| {
                ui.add_space(24.);
                ui.horizontal(|ui| {
                    ui.add_space(8.);
                    ui.label(
                        RichText::new("채팅")
                            .family(egui::FontFamily::Name("semibold".into()))
                            .size(26.),
                    );
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.add_enabled_ui(!self.busy, |ui| {
                            if icon_button(ui, Icon::Refresh, "목록 새로고침", false).clicked()
                            {
                                self.load();
                            }
                        });
                        if icon_button(ui, Icon::Search, "채팅방 검색", self.search_open).clicked()
                        {
                            self.search_open = !self.search_open;
                            self.focus_search = self.search_open;
                            if !self.search_open {
                                self.query.clear();
                                self.filter();
                            }
                        }
                    });
                });
                ui.add_space(16.);
                ui.horizontal(|ui| {
                    ui.add_space(8.);
                    if pill(ui, "전체", !self.selected_only).clicked() {
                        self.selected_only = false;
                        self.filter();
                    }
                    if pill(
                        ui,
                        &format!("선택한 채팅  {}", self.selected.len()),
                        self.selected_only,
                    )
                    .clicked()
                    {
                        self.selected_only = true;
                        self.filter();
                    }
                });
                if self.search_open {
                    ui.add_space(8.);
                    egui::Frame::NONE
                        .fill(FIELD)
                        .corner_radius(8)
                        .inner_margin(10)
                        .show(ui, |ui| {
                            ui.horizontal(|ui| {
                                let search = ui.add(
                                    egui::TextEdit::singleline(&mut self.query)
                                        .frame(false)
                                        .hint_text("채팅방 검색")
                                        .desired_width(ui.available_width() - 46.),
                                );
                                if self.focus_search {
                                    search.request_focus();
                                    self.focus_search = false;
                                }
                                if search.changed() {
                                    self.filter();
                                }
                                if icon_button(ui, Icon::Close, "검색 지우기", false).clicked()
                                {
                                    self.query.clear();
                                    self.filter();
                                }
                            });
                        });
                }
                ui.add_space(10.);
                ui.add_enabled_ui(!self.busy, |ui| {
                    ui.horizontal(|ui| {
                        ui.add_space(8.);
                        if ui
                            .add(
                                egui::Button::new(
                                    RichText::new(if self.query.is_empty() {
                                        "전체 선택"
                                    } else {
                                        "검색 결과 선택"
                                    })
                                    .size(12.)
                                    .color(MUTED),
                                )
                                .frame(false),
                            )
                            .clicked()
                        {
                            if let Some(cat) = &self.catalog {
                                for &i in &self.visible {
                                    if cat.rooms[i].selectable {
                                        self.selected.insert(cat.rooms[i].key.clone());
                                    }
                                }
                            }
                            self.filter();
                        }
                        if ui
                            .add(
                                egui::Button::new(
                                    RichText::new("선택 해제").size(12.).color(MUTED),
                                )
                                .frame(false),
                            )
                            .clicked()
                        {
                            self.selected.clear();
                            self.filter();
                        }
                    });
                });
                ui.add_space(6.);
                egui::TopBottomPanel::bottom("list-footer")
                    .exact_height(42.)
                    .frame(
                        egui::Frame::NONE
                            .fill(LIST)
                            .inner_margin(egui::Margin::symmetric(8, 12)),
                    )
                    .show_inside(ui, |ui| {
                        let count = self.catalog.as_ref().map(|c| c.rooms.len()).unwrap_or(0);
                        ui.label(
                            RichText::new(if self.busy && self.catalog.is_none() {
                                "채팅 목록을 불러오는 중…".into()
                            } else {
                                format!("채팅 {count}개")
                            })
                            .size(12.)
                            .color(MUTED),
                        );
                    });
                if let Some(cat) = &self.catalog {
                    if self.visible.is_empty() {
                        ui.add_space(40.);
                        ui.vertical_centered(|ui| {
                            ui.label(
                                RichText::new(if self.selected_only {
                                    "선택한 채팅방이 없습니다"
                                } else {
                                    "검색 결과가 없습니다"
                                })
                                .color(MUTED),
                            );
                        });
                        return;
                    }
                    let mut changed = false;
                    ui.spacing_mut().item_spacing.y = 0.;
                    egui::ScrollArea::vertical()
                        .id_salt("chat-list")
                        .auto_shrink([false, false])
                        .show_rows(ui, ROW_HEIGHT, self.visible.len(), |ui, range| {
                            for row in range {
                                let i = self.visible[row];
                                let checked = self.selected.contains(&cat.rooms[i].key);
                                if room_row(
                                    ui,
                                    &cat.rooms[i],
                                    checked,
                                    !self.busy && cat.rooms[i].selectable,
                                ) {
                                    if checked {
                                        self.selected.remove(&cat.rooms[i].key);
                                    } else {
                                        self.selected.insert(cat.rooms[i].key.clone());
                                    }
                                    changed = true;
                                }
                            }
                        });
                    if changed && self.selected_only {
                        self.filter();
                    }
                } else {
                    ui.add_space(40.);
                    ui.vertical_centered(|ui| {
                        ui.label(
                            RichText::new(if self.busy {
                                "채팅 목록을 불러오고 있습니다"
                            } else {
                                "채팅 목록을 불러와 주세요"
                            })
                            .color(MUTED),
                        );
                        ui.add_space(8.);
                        if ui
                            .add_enabled(!self.busy, egui::Button::new("목록 불러오기"))
                            .clicked()
                        {
                            self.load();
                        }
                    });
                }
            });
    }

    fn conversation(&mut self, ctx: &egui::Context) {
        egui::CentralPanel::default()
            .frame(egui::Frame::NONE.fill(CHAT))
            .show(ctx, |ui| {
                egui::TopBottomPanel::top("conversation-header")
                    .exact_height(92.)
                    .frame(
                        egui::Frame::NONE
                            .fill(CHAT)
                            .inner_margin(egui::Margin::symmetric(24, 24)),
                    )
                    .show_inside(ui, |ui| {
                        ui.horizontal(|ui| {
                            let (rect, _) =
                                ui.allocate_exact_size(Vec2::splat(44.), egui::Sense::hover());
                            avatar(ui.painter(), rect, true);
                            ui.vertical(|ui| {
                                ui.label(
                                    RichText::new(if self.history {
                                        "진행 내역"
                                    } else {
                                        "메시지 작성"
                                    })
                                    .size(20.)
                                    .strong(),
                                );
                                ui.label(
                                    RichText::new(format!("{}개 채팅방 선택", self.selected.len()))
                                        .size(12.)
                                        .color(MUTED),
                                );
                            });
                            ui.with_layout(
                                egui::Layout::right_to_left(egui::Align::Center),
                                |ui| {
                                    if self.history {
                                        if icon_button(
                                            ui,
                                            Icon::Back,
                                            "메시지 작성으로 돌아가기",
                                            true,
                                        )
                                        .clicked()
                                        {
                                            self.history = false;
                                        }
                                    } else if icon_button(ui, Icon::History, "진행 내역", false)
                                        .clicked()
                                    {
                                        self.history = true;
                                    }
                                },
                            );
                        });
                    });
                egui::TopBottomPanel::bottom("job-status")
                    .exact_height(40.)
                    .frame(
                        egui::Frame::NONE
                            .fill(LIST)
                            .inner_margin(egui::Margin::symmetric(20, 6)),
                    )
                    .show_inside(ui, |ui| {
                        ui.horizontal(|ui| {
                            if self.busy {
                                ui.spinner();
                                if ui.small_button("중지").clicked() {
                                    self.stop.store(true, Ordering::Relaxed);
                                }
                            }
                            ui.add(
                                egui::Label::new(
                                    RichText::new(&self.status).size(12.).color(MUTED),
                                )
                                .truncate(),
                            )
                            .on_hover_text(&self.status);
                        });
                    });
                if self.history {
                    self.history_view(ui);
                } else {
                    self.editor(ui);
                    self.draft_preview(ui);
                }
            });
    }

    fn editor(&mut self, ui: &mut egui::Ui) {
        let height = if self.photos.is_empty() { 230. } else { 314. };
        egui::TopBottomPanel::bottom("composer")
            .exact_height(height)
            .resizable(false)
            .frame(
                egui::Frame::NONE
                    .fill(LIST)
                    .inner_margin(egui::Margin::symmetric(20, 14)),
            )
            .show_inside(ui, |ui| {
                ui.add_enabled_ui(!self.busy, |ui| {
                    egui::ScrollArea::vertical()
                        .id_salt("message-input-scroll")
                        .max_height(108.)
                        .min_scrolled_height(108.)
                        .show(ui, |ui| {
                            ui.add(
                                egui::TextEdit::multiline(&mut self.message)
                                    .id_salt("message-input")
                                    .frame(false)
                                    .hint_text(RichText::new("메시지 입력").color(MUTED))
                                    .font(egui::FontId::proportional(16.))
                                    .desired_width(f32::INFINITY)
                                    .desired_rows(4),
                            );
                        });
                    if !self.photos.is_empty() {
                        let mut remove = None;
                        egui::ScrollArea::horizontal()
                            .id_salt("photo-strip")
                            .max_height(76.)
                            .show(ui, |ui| {
                                ui.horizontal(|ui| {
                                    for (i, texture) in self.textures.iter().enumerate() {
                                        ui.push_id(i, |ui| {
                                            let size = texture.size_vec2();
                                            ui.image((
                                                texture.id(),
                                                size * (60. / size.max_elem()),
                                            ))
                                            .on_hover_text(self.photos[i].description());
                                            if icon_button(ui, Icon::Close, "사진 제거", false)
                                                .clicked()
                                            {
                                                remove = Some(i);
                                            }
                                        });
                                    }
                                });
                            });
                        if let Some(i) = remove {
                            self.photos.remove(i);
                            let _ = self.textures.remove(i);
                        }
                        ui.add_space(8.);
                    }
                    ui.add_space(6.);
                    ui.horizontal(|ui| {
                        send_toggle(ui, &mut self.live);
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            ui.add(
                                egui::DragValue::new(&mut self.interval)
                                    .speed(0.1)
                                    .range(0.0..=3600.0)
                                    .suffix(" 초"),
                            );
                            ui.label(RichText::new("전송 간격").size(12.).color(MUTED));
                        });
                    });
                    ui.add_space(8.);
                    ui.horizontal(|ui| {
                        if icon_button(ui, Icon::Plus, "사진 첨부", false).clicked() {
                            self.add_photos();
                        }
                        ui.label(
                            RichText::new(format!("{} / 10,000", self.message.chars().count()))
                                .size(12.)
                                .color(MUTED),
                        );
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            let ready = self.catalog.as_ref().is_some_and(|c| c.complete)
                                && !self.selected.is_empty()
                                && (!self.message.trim().is_empty() || !self.photos.is_empty())
                                && self.message.chars().count() <= 10000;
                            if primary(ui, if self.live { "전송" } else { "대상 확인" }, ready)
                                .clicked()
                            {
                                self.confirm = true;
                            }
                        });
                    });
                });
            });
    }

    fn draft_preview(&self, ui: &mut egui::Ui) {
        egui::Frame::NONE.inner_margin(24).show(ui, |ui| {
            if self.message.trim().is_empty() && self.photos.is_empty() {
                ui.add_space((ui.available_height() * 0.35).max(12.));
                ui.vertical_centered(|ui| {
                    let (rect, _) = ui.allocate_exact_size(Vec2::splat(36.), egui::Sense::hover());
                    icon(
                        ui.painter(),
                        rect,
                        Icon::Chat,
                        Color32::from_gray(79),
                        false,
                    );
                    ui.add_space(12.);
                    ui.label(
                        RichText::new("전할 이야기를 작성해 주세요")
                            .color(MUTED)
                            .size(16.),
                    );
                    ui.label(
                        RichText::new("선택한 채팅방에 각각 전달됩니다")
                            .color(MUTED)
                            .size(12.),
                    );
                });
                return;
            }
            let (badge_row, _) =
                ui.allocate_exact_size(Vec2::new(ui.available_width(), 28.), egui::Sense::hover());
            let badge = egui::Rect::from_center_size(badge_row.center(), Vec2::new(88., 28.));
            ui.painter().rect_filled(badge, 14, RAIL);
            ui.painter().text(
                badge.center(),
                egui::Align2::CENTER_CENTER,
                "미리보기",
                egui::FontId::proportional(12.),
                MUTED,
            );
            ui.add_space(24.);
            egui::ScrollArea::vertical()
                .id_salt("draft-preview")
                .auto_shrink([false, false])
                .stick_to_bottom(true)
                .show(ui, |ui| {
                    let bubble_width = (ui.available_width() * 0.82).min(440.);
                    if !self.message.trim().is_empty() {
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Min), |ui| {
                            egui::Frame::NONE
                                .fill(YELLOW)
                                .corner_radius(14)
                                .inner_margin(14)
                                .show(ui, |ui| {
                                    ui.set_max_width(bubble_width - 28.);
                                    ui.add(
                                        egui::Label::new(
                                            RichText::new(&self.message).size(16.).color(CHAT),
                                        )
                                        .halign(egui::Align::Min)
                                        .wrap(),
                                    );
                                });
                        });
                        ui.add_space(12.);
                    }
                    for t in &self.textures {
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Min), |ui| {
                            let scale = ((bubble_width.min(280.)) / t.size_vec2().x)
                                .min(220. / t.size_vec2().y)
                                .min(1.);
                            ui.add(
                                egui::Image::new((t.id(), t.size_vec2() * scale)).corner_radius(12),
                            );
                        });
                        ui.add_space(10.);
                    }
                });
        });
    }

    fn history_view(&mut self, ui: &mut egui::Ui) {
        egui::TopBottomPanel::bottom("history-actions")
            .exact_height(72.)
            .frame(
                egui::Frame::NONE
                    .fill(LIST)
                    .inner_margin(egui::Margin::symmetric(20, 16)),
            )
            .show_inside(ui, |ui| {
                ui.horizontal(|ui| {
                    if ui
                        .add_enabled(!self.results.is_empty(), egui::Button::new("CSV 저장"))
                        .clicked()
                    {
                        self.export();
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        if primary(ui, "메시지 작성으로 돌아가기", true).clicked() {
                            self.history = false;
                        }
                    });
                });
            });
        egui::Frame::NONE.inner_margin(24).show(ui, |ui| {
            if self.results.is_empty() {
                ui.add_space(80.);
                ui.vertical_centered(|ui| {
                    ui.label(RichText::new("아직 진행 내역이 없습니다").color(MUTED));
                });
            } else {
                egui::ScrollArea::vertical().id_salt("results").show_rows(
                    ui,
                    92.,
                    self.results.len(),
                    |ui, range| {
                        for i in range {
                            let r = &self.results[i];
                            egui::Frame::NONE
                                .fill(LIST)
                                .corner_radius(10)
                                .inner_margin(14)
                                .show(ui, |ui| {
                                    ui.set_min_width(ui.available_width());
                                    ui.horizontal(|ui| {
                                        ui.label(RichText::new(&r.room.name).size(16.).strong());
                                        ui.label(RichText::new(&r.state).size(12.).color(
                                            if r.state == "중단" {
                                                Color32::from_rgb(245, 137, 137)
                                            } else {
                                                Color32::from_rgb(168, 195, 211)
                                            },
                                        ));
                                    });
                                    ui.add(
                                        egui::Label::new(
                                            RichText::new(&r.detail).size(13.).color(MUTED),
                                        )
                                        .truncate(),
                                    )
                                    .on_hover_text(&r.detail);
                                });
                        }
                    },
                );
            }
        });
    }

    fn settings_view(&mut self, ctx: &egui::Context) {
        egui::CentralPanel::default().frame(egui::Frame::NONE.fill(LIST).inner_margin(32)).show(ctx, |ui| {
            ui.label(RichText::new("연결 설정").size(26.).strong());
            ui.add_space(32.);
            ui.label(RichText::new("카카오톡 연결").size(18.).strong());
            ui.label(RichText::new("카카오톡 메인 창의 채팅 탭을 열어 주세요.").color(MUTED));
            ui.add_space(12.);
            ui.horizontal(|ui| {
                if ui.button("손쉬운 사용 설정 열기").clicked() {
                    #[cfg(target_os = "macos")]
                    { let _ = std::process::Command::new("open").arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility").spawn(); }
                }
                if ui.add_enabled(!self.busy, egui::Button::new("연결 확인 · 새로고침")).clicked() { self.load(); }
            });
            ui.add_space(20.);
            ui.label(&self.status);
            if self.busy && ui.button("조회 중지").clicked() { self.stop.store(true, Ordering::Relaxed); }
            ui.add_space(32.);
            ui.separator();
            ui.add_space(20.);
            ui.label(RichText::new("사용 안내").size(18.).strong());
            for line in ["카카오톡 접근을 위해 손쉬운 사용에서 이 앱을 허용해 주세요.", "작성 중인 글·사진은 앱을 종료하기 전에 보관해 주세요.", "설정과 전송 이력은 앱을 업데이트해도 유지됩니다."] {
                ui.label(RichText::new(line).size(14.).color(MUTED));
            }
            ui.with_layout(egui::Layout::bottom_up(egui::Align::LEFT), |ui| {
                ui.label(RichText::new(format!("Kakao Friend Sender  {}", env!("CARGO_PKG_VERSION"))).size(12.).color(MUTED));
            });
        });
    }
}
impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if let Some(path) = self.smoke.clone() {
            self.smoke_frames += 1;
            ctx.request_repaint();
            if self.smoke_frames == 3 {
                ctx.send_viewport_cmd(egui::ViewportCommand::Screenshot(Default::default()));
            }
            for event in ctx.input(|i| i.events.clone()) {
                if let egui::Event::Screenshot { image, .. } = event {
                    let bytes: Vec<u8> = image.pixels.iter().flat_map(|p| p.to_array()).collect();
                    let saved = image::save_buffer(
                        path.with_extension("png"),
                        &bytes,
                        image.width() as u32,
                        image.height() as u32,
                        image::ColorType::Rgba8,
                    )
                    .is_ok();
                    let report = serde_json::json!({"ok":saved,"rooms":10000,"real_sent":0,"width":image.width(),"height":image.height()});
                    let _ = std::fs::write(&path, report.to_string());
                    self.allow_close = true;
                    self.smoke = None;
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            }
            if self.smoke_frames > 300 {
                self.allow_close = true;
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            }
        }
        self.events(ctx);
        if self.busy {
            ctx.request_repaint_after(Duration::from_millis(80));
        }
        if ctx.input(|i| i.viewport().close_requested()) && !self.allow_close {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.close_confirm = true;
        }
        self.navigation(ctx);
        if self.settings {
            self.settings_view(ctx);
        } else {
            self.rooms_panel(ctx);
            self.conversation(ctx);
        }
        if self.confirm {
            egui::Modal::new(egui::Id::new("send-confirm")).show(ctx, |ui| {
                ui.set_min_width(480.);
                ui.heading(if self.live {
                    "전송 전 확인"
                } else {
                    "대상 확인"
                });
                ui.label(format!(
                    "대화방 {}개 · 사진 {}장",
                    self.selected.len(),
                    self.photos.len()
                ));
                let selected: Vec<_> = self
                    .catalog
                    .as_ref()
                    .map(|cat| {
                        cat.rooms
                            .iter()
                            .filter(|r| self.selected.contains(&r.key))
                            .collect()
                    })
                    .unwrap_or_default();
                egui::ScrollArea::vertical()
                    .id_salt("confirm-recipients")
                    .max_height(100.)
                    .show_rows(ui, 24., selected.len(), |ui, range| {
                        for row in range {
                            let name = &selected[row].name;
                            ui.add_sized(
                                [ui.available_width(), 24.],
                                egui::Label::new(name).truncate(),
                            )
                            .on_hover_text(name);
                        }
                    });
                ui.separator();
                egui::ScrollArea::vertical()
                    .id_salt("confirm-message")
                    .max_height(180.)
                    .show(ui, |ui| {
                        ui.label(&self.message);
                    });
                egui::ScrollArea::horizontal()
                    .id_salt("confirm-photos")
                    .max_height(150.)
                    .show(ui, |ui| {
                        ui.horizontal(|ui| {
                            for (i, t) in self.textures.iter().enumerate() {
                                ui.vertical(|ui| {
                                    ui.label(&self.photos[i].name)
                                        .on_hover_text(self.photos[i].description());
                                    ui.image((t.id(), t.size_vec2() * (100. / t.size_vec2().y)));
                                });
                            }
                        });
                    });
                ui.horizontal(|ui| {
                    if ui.button("취소").clicked() {
                        self.confirm = false;
                    }
                    if primary(
                        ui,
                        if self.live {
                            "확인하고 전송"
                        } else {
                            "입력 없이 대상 확인"
                        },
                        !self.busy,
                    )
                    .clicked()
                    {
                        self.run();
                    }
                });
            });
        }
        if self.close_confirm {
            egui::Modal::new(egui::Id::new("close-confirm")).show(ctx, |ui| {
                ui.label("작성 중인 글·사진은 저장되지 않습니다. 종료할까요?");
                ui.horizontal(|ui| {
                    if ui.button("계속 작성").clicked() {
                        self.close_confirm = false;
                    }
                    if ui.button("종료").clicked() {
                        self.close_confirm = false;
                        if self.busy {
                            self.stop.store(true, Ordering::Relaxed);
                            self.close_after_job = true;
                        } else {
                            self.allow_close = true;
                            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                        }
                    }
                });
            });
        }
    }
}
