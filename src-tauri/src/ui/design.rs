use crate::core::Room;
use eframe::egui::{self, pos2, vec2, Color32, FontId, Rect, Response, RichText, Stroke, Vec2};

pub const RAIL: Color32 = Color32::from_gray(45);
pub const LIST: Color32 = Color32::from_gray(34);
pub const CHAT: Color32 = Color32::from_gray(20);
pub const FIELD: Color32 = Color32::from_gray(47);
pub const LINE: Color32 = Color32::from_gray(54);
pub const TEXT: Color32 = Color32::from_gray(238);
pub const MUTED: Color32 = Color32::from_gray(151);
pub const YELLOW: Color32 = Color32::from_rgb(254, 229, 0);
pub const ROW_HEIGHT: f32 = 86.;

pub fn apply(ctx: &egui::Context) {
    let mut style = (*ctx.style()).clone();
    style.visuals = egui::Visuals::dark();
    style.visuals.override_text_color = Some(TEXT);
    style.visuals.panel_fill = LIST;
    style.visuals.window_fill = LIST;
    style.visuals.extreme_bg_color = CHAT;
    style.visuals.faint_bg_color = FIELD;
    style.visuals.selection.bg_fill = Color32::from_rgb(80, 73, 20);
    style.visuals.selection.stroke.color = TEXT;
    style.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0_f32, LINE);
    style.visuals.widgets.noninteractive.fg_stroke = Stroke::new(1.0_f32, MUTED);
    style.visuals.widgets.inactive.weak_bg_fill = FIELD;
    style.visuals.widgets.inactive.bg_fill = FIELD;
    style.visuals.widgets.inactive.bg_stroke = Stroke::NONE;
    style.visuals.widgets.hovered.weak_bg_fill = Color32::from_gray(62);
    style.visuals.widgets.hovered.bg_stroke = Stroke::NONE;
    style.visuals.widgets.active.bg_stroke = Stroke::NONE;
    style.visuals.widgets.inactive.corner_radius = 8.into();
    style.visuals.widgets.hovered.corner_radius = 8.into();
    style.visuals.widgets.active.corner_radius = 8.into();
    style.spacing.item_spacing = vec2(10., 8.);
    style.spacing.button_padding = vec2(14., 10.);
    style.spacing.interact_size = vec2(32., 32.);
    style.spacing.scroll.bar_width = 4.;
    style
        .text_styles
        .insert(egui::TextStyle::Body, FontId::proportional(15.));
    style
        .text_styles
        .insert(egui::TextStyle::Button, FontId::proportional(14.));
    style
        .text_styles
        .insert(egui::TextStyle::Small, FontId::proportional(12.));
    style
        .text_styles
        .insert(egui::TextStyle::Heading, FontId::proportional(24.));
    ctx.set_style(style);
}

#[derive(Clone, Copy)]
pub enum Icon {
    Chat,
    History,
    Settings,
    Search,
    Refresh,
    Plus,
    Close,
    Back,
}

pub fn icon(p: &egui::Painter, rect: Rect, icon: Icon, color: Color32, filled: bool) {
    let c = rect.center();
    let s = rect.width().min(rect.height()) / 24.;
    let v = |x, y| c + vec2(x * s, y * s);
    let stroke = Stroke::new(1.7 * s, color);
    let line = |a: (f32, f32), b: (f32, f32)| {
        p.line_segment([v(a.0, a.1), v(b.0, b.1)], stroke);
    };
    match icon {
        Icon::Chat => {
            let r = Rect::from_min_max(v(-9., -8.), v(9., 6.));
            if filled {
                p.rect_filled(r, (7. * s) as u8, color);
                p.add(egui::Shape::convex_polygon(
                    vec![v(-6., 3.), v(-6., 10.), v(1., 4.)],
                    color,
                    Stroke::NONE,
                ));
            } else {
                p.rect_stroke(r, (7. * s) as u8, stroke, egui::StrokeKind::Middle);
                line((-6., 6.), (-6., 10.));
                line((-6., 10.), (-1., 6.));
            }
        }
        Icon::History => {
            p.circle_stroke(c, 9. * s, stroke);
            line((0., -5.), (0., 0.));
            line((0., 0.), (4., 2.));
        }
        Icon::Settings => {
            p.circle_stroke(c, 6.8 * s, stroke);
            p.circle_stroke(c, 2.5 * s, stroke);
            for i in 0..8 {
                let a = i as f32 * std::f32::consts::TAU / 8.;
                p.line_segment(
                    [
                        c + vec2(a.cos(), a.sin()) * 7. * s,
                        c + vec2(a.cos(), a.sin()) * 10. * s,
                    ],
                    Stroke::new(3. * s, color),
                );
            }
        }
        Icon::Search => {
            p.circle_stroke(v(-2., -2.), 7.5 * s, stroke);
            line((4., 4.), (10., 10.));
        }
        Icon::Refresh => {
            let points: Vec<_> = (0..25)
                .map(|i| {
                    let a = 0.4 + i as f32 * 5.1 / 24.;
                    v(a.cos() * 8., a.sin() * 8.)
                })
                .collect();
            p.add(egui::Shape::line(points, stroke));
            line((5., -8.), (5., -2.));
            line((5., -2.), (0., -3.));
        }
        Icon::Plus => {
            line((-8., 0.), (8., 0.));
            line((0., -8.), (0., 8.));
        }
        Icon::Close => {
            line((-5., -5.), (5., 5.));
            line((-5., 5.), (5., -5.));
        }
        Icon::Back => {
            line((-8., 0.), (8., 0.));
            line((-8., 0.), (-2., -6.));
            line((-8., 0.), (-2., 6.));
        }
    }
}

pub fn icon_button(ui: &mut egui::Ui, glyph: Icon, label: &str, active: bool) -> Response {
    let (rect, response) = ui.allocate_exact_size(vec2(36., 36.), egui::Sense::click());
    response.widget_info(|| {
        egui::WidgetInfo::labeled(egui::WidgetType::Button, ui.is_enabled(), label)
    });
    if response.hovered() && ui.is_enabled() {
        ui.painter().rect_filled(rect, 18, FIELD);
    }
    if response.has_focus() {
        ui.painter().rect_stroke(
            rect,
            18,
            Stroke::new(1.0_f32, MUTED),
            egui::StrokeKind::Inside,
        );
    }
    icon(
        ui.painter(),
        rect.shrink(7.),
        glyph,
        if active { TEXT } else { MUTED },
        active,
    );
    response.on_hover_text(label)
}

pub fn pill(ui: &mut egui::Ui, text: &str, active: bool) -> Response {
    ui.add(
        egui::Button::new(
            RichText::new(text)
                .size(15.)
                .color(if active { LIST } else { TEXT }),
        )
        .fill(if active { TEXT } else { RAIL })
        .corner_radius(22)
        .min_size(vec2(60., 38.)),
    )
}

pub fn primary(ui: &mut egui::Ui, label: &str, enabled: bool) -> Response {
    ui.add_enabled(
        enabled,
        egui::Button::new(
            RichText::new(label)
                .strong()
                .color(if enabled { CHAT } else { MUTED }),
        )
        .fill(if enabled { YELLOW } else { FIELD })
        .corner_radius(8)
        .min_size(vec2(110., 40.)),
    )
}

pub fn send_toggle(ui: &mut egui::Ui, value: &mut bool) {
    let (rect, response) = ui.allocate_exact_size(vec2(110., 32.), egui::Sense::click());
    response.widget_info(|| {
        egui::WidgetInfo::selected(
            egui::WidgetType::Checkbox,
            ui.is_enabled(),
            *value,
            "실제 전송",
        )
    });
    if response.clicked() {
        response.request_focus();
    }
    if ui.is_enabled()
        && (response.clicked()
            || response.has_focus() && ui.input(|i| i.key_pressed(egui::Key::Space)))
    {
        *value = !*value;
    }
    let mark = Rect::from_center_size(pos2(rect.left() + 10., rect.center().y), Vec2::splat(18.));
    ui.painter()
        .rect_filled(mark, 4, if *value { YELLOW } else { LIST });
    ui.painter().rect_stroke(
        mark,
        4,
        Stroke::new(1.3_f32, if *value { YELLOW } else { MUTED }),
        egui::StrokeKind::Inside,
    );
    if *value {
        ui.painter().line_segment(
            [mark.min + vec2(4., 9.), mark.min + vec2(8., 13.)],
            Stroke::new(2.0_f32, CHAT),
        );
        ui.painter().line_segment(
            [mark.min + vec2(8., 13.), mark.min + vec2(14., 5.)],
            Stroke::new(2.0_f32, CHAT),
        );
    }
    ui.painter().text(
        pos2(rect.left() + 28., rect.center().y),
        egui::Align2::LEFT_CENTER,
        "실제 전송",
        FontId::proportional(14.),
        TEXT,
    );
    if response.has_focus() {
        ui.painter().rect_stroke(
            rect,
            4,
            Stroke::new(1.0_f32, MUTED),
            egui::StrokeKind::Inside,
        );
    }
}

pub fn avatar(p: &egui::Painter, rect: Rect, enabled: bool) {
    let color = if enabled {
        Color32::from_rgb(146, 198, 239)
    } else {
        Color32::from_gray(77)
    };
    p.rect_filled(rect, (rect.width() * 0.38) as u8, color);
    let face = if enabled {
        Color32::from_rgb(219, 239, 255)
    } else {
        MUTED
    };
    let w = rect.width();
    p.circle_filled(rect.center() - vec2(0., w * 0.12), w * 0.125, face);
    p.rect_filled(
        Rect::from_center_size(rect.center() + vec2(0., w * 0.16), vec2(w * 0.42, w * 0.23)),
        (w * 0.115) as u8,
        face,
    );
}

pub fn room_row(ui: &mut egui::Ui, room: &Room, checked: bool, enabled: bool) -> bool {
    let (rect, response) = ui.allocate_exact_size(
        vec2(ui.available_width(), ROW_HEIGHT),
        if enabled {
            egui::Sense::click()
        } else {
            egui::Sense::hover()
        },
    );
    response.widget_info(|| {
        egui::WidgetInfo::selected(egui::WidgetType::Checkbox, enabled, checked, &room.name)
    });
    let p = ui.painter();
    if checked || response.hovered() {
        p.rect_filled(
            rect,
            8,
            if checked {
                Color32::from_rgb(51, 50, 43)
            } else {
                Color32::from_gray(41)
            },
        );
    }
    if response.has_focus() {
        p.rect_stroke(
            rect.shrink(1.),
            8,
            Stroke::new(1.0_f32, MUTED),
            egui::StrokeKind::Inside,
        );
    }
    avatar(
        p,
        Rect::from_center_size(pos2(rect.left() + 38., rect.center().y), Vec2::splat(52.)),
        room.selectable,
    );
    let color = if room.selectable { TEXT } else { MUTED };
    let mut title = egui::text::LayoutJob::simple(
        room.name.clone(),
        FontId::new(17., egui::FontFamily::Name("semibold".into())),
        color,
        (rect.width() - 120.).max(20.),
    );
    title.wrap.max_rows = 1;
    p.galley(
        pos2(rect.left() + 78., rect.center().y - 20.),
        p.layout_job(title),
        color,
    );
    let note = if !room.selectable {
        &room.note
    } else if checked {
        "전송 대상으로 선택됨"
    } else {
        "대화방"
    };
    let mut detail = egui::text::LayoutJob::simple(
        note.into(),
        FontId::proportional(13.),
        MUTED,
        (rect.width() - 120.).max(20.),
    );
    detail.wrap.max_rows = 1;
    p.galley(
        pos2(rect.left() + 78., rect.center().y + 6.),
        p.layout_job(detail),
        MUTED,
    );
    let mark = Rect::from_center_size(pos2(rect.right() - 20., rect.center().y), Vec2::splat(20.));
    if checked {
        p.circle_filled(mark.center(), 10., YELLOW);
        p.line_segment(
            [mark.min + vec2(5., 10.), mark.min + vec2(9., 14.)],
            Stroke::new(2.0_f32, CHAT),
        );
        p.line_segment(
            [mark.min + vec2(9., 14.), mark.min + vec2(15., 7.)],
            Stroke::new(2.0_f32, CHAT),
        );
    } else {
        p.circle_stroke(
            mark.center(),
            9.,
            Stroke::new(1.3_f32, Color32::from_gray(92)),
        );
    }
    if response.clicked() {
        response.request_focus();
    }
    enabled
        && (response.clicked()
            || response.has_focus() && ui.input(|i| i.key_pressed(egui::Key::Space)))
}
