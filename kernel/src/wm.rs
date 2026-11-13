//! Foundation window manager and desktop shell: wallpaper, icons, windows, taskbar,
//! start menu and the mouse cursor.
use crate::apps::{self, App, AppKind, Key};
use crate::gfx::*;
use crate::mouse::MouseEvent;
use crate::rtc::{self, DateTime};
use crate::sys::{self, Request};
use alloc::boxed::Box;
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

pub const TITLE_H: i32 = 30;
pub const TASKBAR_H: i32 = 44;
const MENU_W: i32 = 240;
const MENU_ITEM_H: i32 = 38;
const MENU_HEADER_H: i32 = 64;
const ICON_CELL: i32 = 92;

pub const ACCENT: Color = 0x4F8CFF;

struct Window {
    id: u32,
    rect: Rect,
    app: Box<dyn App>,
    minimized: bool,
}

impl Window {
    fn content(&self) -> Rect {
        Rect::new(self.rect.x + 1, self.rect.y + TITLE_H, self.rect.w - 2, self.rect.h - TITLE_H - 1)
    }
    fn close_btn(&self) -> Rect {
        Rect::new(self.rect.x + self.rect.w - 26, self.rect.y + 7, 16, 16)
    }
    fn min_btn(&self) -> Rect {
        Rect::new(self.rect.x + self.rect.w - 48, self.rect.y + 7, 16, 16)
    }
}

pub struct Desktop {
    w: i32,
    h: i32,
    windows: Vec<Window>, // last = topmost
    next_id: u32,
    mx: i32,
    my: i32,
    left: bool,
    drag: Option<(u32, i32, i32)>,
    capture: Option<u32>,
    menu_open: bool,
    hover_menu: Option<usize>,
    time: DateTime,
    last_tick: u64,
    pub dirty: bool,
    opened: u32,
}

impl Desktop {
    pub fn new(w: i32, h: i32) -> Self {
        Self {
            w,
            h,
            windows: Vec::new(),
            next_id: 1,
            mx: w / 2,
            my: h / 2,
            left: false,
            drag: None,
            capture: None,
            menu_open: false,
            hover_menu: None,
            time: rtc::now(),
            last_tick: 0,
            dirty: true,
            opened: 0,
        }
    }

    pub fn open(&mut self, kind: AppKind) {
        self.open_app(apps::create(kind));
    }

    pub fn open_app(&mut self, app: Box<dyn App>) {
        let (cw, ch) = app.size();
        let ww = (cw + 2).min(self.w - 20);
        let wh = (ch + TITLE_H + 1).min(self.h - TASKBAR_H - 20);
        let n = (self.opened % 8) as i32;
        self.opened += 1;
        let x = (140 + n * 36).min(self.w - ww - 10).max(0);
        let y = (40 + n * 30).min(self.h - TASKBAR_H - wh - 10).max(0);
        let id = self.next_id;
        self.next_id += 1;
        crate::klog!("wm: opened window #{} '{}'", id, app.title());
        self.windows.push(Window { id, rect: Rect::new(x, y, ww, wh), app, minimized: false });
        self.dirty = true;
    }

    fn index_of(&self, id: u32) -> Option<usize> {
        self.windows.iter().position(|w| w.id == id)
    }

    fn raise(&mut self, idx: usize) {
        let w = self.windows.remove(idx);
        self.windows.push(w);
    }

    fn focused(&mut self) -> Option<&mut Window> {
        self.windows.iter_mut().rev().find(|w| !w.minimized)
    }

    fn focused_id(&self) -> Option<u32> {
        self.windows.iter().rev().find(|w| !w.minimized).map(|w| w.id)
    }

    // ----------------------------------------------------------------- input

    pub fn key(&mut self, k: Key) {
        if k == Key::Esc && self.menu_open {
            self.menu_open = false;
        } else if let Some(w) = self.focused() {
            w.app.key(k);
        }
        self.dirty = true;
    }

    pub fn mouse(&mut self, ev: MouseEvent) {
        self.mx = (self.mx + ev.dx).clamp(0, self.w - 1);
        self.my = (self.my + ev.dy).clamp(0, self.h - 1);
        let pressed = ev.left && !self.left;
        let released = !ev.left && self.left;
        self.left = ev.left;
        let (mx, my) = (self.mx, self.my);

        if let Some((id, ox, oy)) = self.drag {
            if ev.left {
                if let Some(i) = self.index_of(id) {
                    let max_y = self.h - TASKBAR_H - TITLE_H;
                    let r = &mut self.windows[i].rect;
                    r.x = (mx - ox).clamp(-r.w + 80, self.w - 80);
                    r.y = (my - oy).clamp(0, max_y);
                }
            } else {
                self.drag = None;
            }
        } else if let Some(id) = self.capture {
            if let Some(i) = self.index_of(id) {
                let c = self.windows[i].content();
                if ev.left {
                    self.windows[i].app.mouse_drag(mx - c.x, my - c.y);
                } else if released {
                    self.windows[i].app.mouse_up(mx - c.x, my - c.y);
                }
            }
            if !ev.left {
                self.capture = None;
            }
        }

        if pressed {
            self.click(mx, my);
        }
        if self.menu_open {
            self.hover_menu = self.menu_item_at(mx, my);
        }
        self.dirty = true;
    }

    fn menu_rect(&self) -> Rect {
        let h = MENU_HEADER_H + apps::ALL.len() as i32 * MENU_ITEM_H + 64;
        Rect::new(6, self.h - TASKBAR_H - h - 6, MENU_W, h)
    }

    fn menu_item_at(&self, x: i32, y: i32) -> Option<usize> {
        let m = self.menu_rect();
        if !m.contains(x, y) {
            return None;
        }
        let ry = y - m.y - MENU_HEADER_H;
        if ry < 0 {
            return None;
        }
        let i = (ry / MENU_ITEM_H) as usize;
        if i < apps::ALL.len() {
            Some(i)
        } else if ry >= apps::ALL.len() as i32 * MENU_ITEM_H + 16 {
            Some(usize::MAX) // power row
        } else {
            None
        }
    }

    fn start_btn(&self) -> Rect {
        Rect::new(6, self.h - TASKBAR_H + 6, 132, TASKBAR_H - 12)
    }

    fn task_btn(&self, i: usize) -> Rect {
        let n = self.windows.len().max(1) as i32;
        let avail = self.w - 150 - 140;
        let slot = (avail / n).min(168).max(48);
        Rect::new(150 + i as i32 * slot, self.h - TASKBAR_H + 6, slot - 8, TASKBAR_H - 12)
    }

    fn icon_rect(&self, i: usize) -> Rect {
        let per_col = ((self.h - TASKBAR_H - 16) / ICON_CELL).max(1) as usize;
        Rect::new(
            12 + (i / per_col) as i32 * ICON_CELL,
            16 + (i % per_col) as i32 * ICON_CELL,
            ICON_CELL - 8,
            ICON_CELL - 8,
        )
    }

    fn click(&mut self, x: i32, y: i32) {
        // Start menu.
        if self.menu_open {
            self.menu_open = false;
            match self.menu_item_at(x, y) {
                Some(usize::MAX) => {
                    let m = self.menu_rect();
                    let row_y = m.y + MENU_HEADER_H + apps::ALL.len() as i32 * MENU_ITEM_H + 16;
                    if Rect::new(m.x + 12, row_y, (MENU_W - 36) / 2, 36).contains(x, y) {
                        sys::reboot();
                    } else if Rect::new(m.x + 24 + (MENU_W - 36) / 2, row_y, (MENU_W - 36) / 2, 36).contains(x, y) {
                        sys::shutdown();
                    }
                    return;
                }
                Some(i) => {
                    self.open(apps::ALL[i]);
                    return;
                }
                None => {
                    if self.menu_rect().contains(x, y) {
                        self.menu_open = true;
                        return;
                    }
                    if self.start_btn().contains(x, y) {
                        return;
                    }
                }
            }
        }

        // Taskbar.
        if y >= self.h - TASKBAR_H {
            if self.start_btn().contains(x, y) {
                self.menu_open = true;
                self.hover_menu = None;
                return;
            }
            let focused = self.focused_id();
            for i in 0..self.windows.len() {
                if self.task_btn(i).contains(x, y) {
                    let id = self.windows[i].id;
                    if Some(id) == focused {
                        self.windows[i].minimized = true;
                    } else {
                        self.windows[i].minimized = false;
                        self.raise(i);
                    }
                    return;
                }
            }
            return;
        }

        // Windows, top-most first.
        for i in (0..self.windows.len()).rev() {
            let w = &self.windows[i];
            if w.minimized || !w.rect.contains(x, y) {
                continue;
            }
            self.raise(i);
            let top = self.windows.len() - 1;
            let w = &mut self.windows[top];
            if y < w.rect.y + TITLE_H {
                if w.close_btn().inset(-3).contains(x, y) {
                    crate::klog!("wm: closed window #{}", w.id);
                    self.windows.pop();
                } else if w.min_btn().inset(-3).contains(x, y) {
                    w.minimized = true;
                } else {
                    self.drag = Some((w.id, x - w.rect.x, y - w.rect.y));
                }
            } else {
                let c = w.content();
                w.app.mouse_down(x - c.x, y - c.y);
                self.capture = Some(w.id);
            }
            return;
        }

        // Desktop icons.
        for (i, kind) in apps::ALL.iter().enumerate() {
            if self.icon_rect(i).contains(x, y) {
                self.open(*kind);
                return;
            }
        }
    }

    /// Called from the main loop; returns true if a redraw is needed.
    pub fn tick(&mut self) {
        for r in sys::take_requests() {
            match r {
                Request::Open(k) => self.open(k),
                Request::Edit(f) => self.open_app(Box::new(apps::Notepad::with_file(&f))),
            }
        }
        let t = sys::ticks();
        if t / 10 != self.last_tick / 10 {
            self.last_tick = t;
            let now = rtc::now();
            if now != self.time {
                self.time = now;
                self.dirty = true;
            }
            for w in self.windows.iter_mut() {
                if !w.minimized && w.app.tick() {
                    self.dirty = true;
                }
            }
        }
        let before = self.windows.len();
        self.windows.retain(|w| !w.app.closed());
        if self.windows.len() != before {
            self.dirty = true;
        }
    }

    // --------------------------------------------------------------- drawing

    pub fn draw(&mut self, c: &mut Canvas) {
        self.draw_wallpaper(c);
        for (i, kind) in apps::ALL.iter().enumerate() {
            let r = self.icon_rect(i);
            let hover = r.contains(self.mx, self.my) && !self.menu_open;
            if hover {
                c.blend_round_rect(r.x, r.y, r.w, r.h, 10, 0xFFFFFF, 40);
            }
            apps::draw_icon(c, *kind, r.x + (r.w - 48) / 2, r.y + 6);
            let label = kind.name();
            let lw = text_width(label, FONT);
            c.text(r.x + (r.w - lw) / 2 + 1, r.y + 60, label, FONT, 0x000000);
            c.text(r.x + (r.w - lw) / 2, r.y + 59, label, FONT, 0xFFFFFF);
        }

        let focused = self.focused_id();
        for w in self.windows.iter_mut() {
            if !w.minimized {
                draw_window(c, w, Some(w.id) == focused);
            }
        }

        self.draw_taskbar(c, focused);
        if self.menu_open {
            self.draw_menu(c);
        }
        draw_cursor(c, self.mx, self.my);

        *sys::WINDOWS.lock() = self.windows.iter().map(|w| w.app.title()).collect();
        self.dirty = false;
    }

    fn draw_wallpaper(&self, c: &mut Canvas) {
        let h = self.h - TASKBAR_H;
        let mid = h * 3 / 5;
        c.gradient_v(0, 0, self.w, mid, 0x0B1A3A, 0x23407A);
        c.gradient_v(0, mid, self.w, h - mid, 0x23407A, 0x5A3F8C);
        // Soft "horizon" glow.
        c.blend_rect(0, mid - 2, self.w, 4, 0xFFFFFF, 18);
        // Watermark logo + wordmark.
        let cx = self.w / 2 + 60;
        let cy = h / 2 - 40;
        draw_logo(c, cx - 70, cy - 70, 140, 0xFFFFFF, 28);
        let word = "F O U N D A T I O N";
        let ww = text_width(word, FONT_LARGE);
        for (i, ch) in word.chars().enumerate() {
            draw_char_alpha(c, cx - ww / 2 + i as i32 * FONT_LARGE.cw(), cy + 92, ch, 60);
        }
    }

    fn draw_taskbar(&self, c: &mut Canvas, focused: Option<u32>) {
        let y = self.h - TASKBAR_H;
        c.blend_rect(0, y, self.w, TASKBAR_H, 0x0A0F1C, 225);
        c.fill_rect(0, y, self.w, 1, 0x34405C);

        // Start button.
        let sb = self.start_btn();
        let hot = self.menu_open || sb.contains(self.mx, self.my);
        c.fill_round_rect(sb.x, sb.y, sb.w, sb.h, 8, if hot { 0x3B6FE0 } else { ACCENT });
        draw_logo(c, sb.x + 10, sb.y + 5, 22, 0xFFFFFF, 255);
        c.text(sb.x + 40, sb.y + (sb.h - 16) / 2, "Foundation", FONT_BOLD, 0xFFFFFF);

        // Window buttons.
        for (i, w) in self.windows.iter().enumerate() {
            let r = self.task_btn(i);
            let active = Some(w.id) == focused;
            let bg = if active { 0x2A3550 } else if w.minimized { 0x141A2A } else { 0x1C2438 };
            c.fill_round_rect(r.x, r.y, r.w, r.h, 6, bg);
            if active {
                c.fill_rect(r.x + 10, r.y + r.h - 3, r.w - 20, 2, ACCENT);
            }
            let mut t = w.app.title();
            let max_chars = ((r.w - 20) / FONT.cw()).max(1) as usize;
            if t.chars().count() > max_chars {
                t = t.chars().take(max_chars.saturating_sub(1)).collect::<String>() + "~";
            }
            c.set_clip(r);
            c.text(r.x + 10, r.y + (r.h - 16) / 2, &t, FONT, if w.minimized { 0x8090B0 } else { 0xE8ECF5 });
            c.reset_clip();
        }

        // Clock.
        let t = self.time;
        let time = format!("{:02}:{:02}:{:02}", t.hour, t.minute, t.second);
        let date = format!("{} {} {}", t.day, rtc::MONTHS[(t.month.max(1) as usize - 1) % 12], t.year);
        let tw = text_width(&time, FONT_BOLD);
        let dw = text_width(&date, FONT);
        c.text(self.w - 16 - tw, y + 5, &time, FONT_BOLD, 0xFFFFFF);
        c.text(self.w - 16 - dw, y + 23, &date, FONT, 0x9AA8C7);
    }

    fn draw_menu(&self, c: &mut Canvas) {
        let m = self.menu_rect();
        c.blend_round_rect(m.x + 4, m.y + 6, m.w, m.h, 12, 0x000000, 90);
        c.fill_round_rect(m.x, m.y, m.w, m.h, 12, 0x161D2E);
        c.fill_round_rect(m.x, m.y, m.w, MENU_HEADER_H, 12, 0x24304A);
        c.fill_rect(m.x, m.y + MENU_HEADER_H - 12, m.w, 12, 0x24304A);
        draw_logo(c, m.x + 14, m.y + 14, 36, 0xFFFFFF, 255);
        c.text(m.x + 62, m.y + 12, "Foundation OS", FONT_MED, 0xFFFFFF);
        c.text(m.x + 62, m.y + 36, "version 0.1", FONT, 0x9AA8C7);
        for (i, kind) in apps::ALL.iter().enumerate() {
            let y = m.y + MENU_HEADER_H + i as i32 * MENU_ITEM_H;
            if self.hover_menu == Some(i) {
                c.fill_round_rect(m.x + 6, y + 2, m.w - 12, MENU_ITEM_H - 4, 6, 0x2F3E60);
            }
            c.fill_round_rect(m.x + 16, y + 9, 20, 20, 5, kind.color());
            c.text(m.x + 48, y + 11, kind.name(), FONT, 0xE8ECF5);
        }
        let row_y = m.y + MENU_HEADER_H + apps::ALL.len() as i32 * MENU_ITEM_H + 16;
        c.fill_rect(m.x + 12, row_y - 9, m.w - 24, 1, 0x2A3550);
        let bw = (MENU_W - 36) / 2;
        c.fill_round_rect(m.x + 12, row_y, bw, 36, 6, 0x2A3550);
        c.text_centered(Rect::new(m.x + 12, row_y, bw, 36), "Restart", FONT, 0xE8ECF5);
        c.fill_round_rect(m.x + 24 + bw, row_y, bw, 36, 6, 0x8C2F39);
        c.text_centered(Rect::new(m.x + 24 + bw, row_y, bw, 36), "Shut down", FONT, 0xFFFFFF);
    }
}

fn draw_char_alpha(c: &mut Canvas, x: i32, y: i32, ch: char, alpha: u32) {
    // Render into a tiny scratch canvas then blend white with scaled coverage.
    let f = FONT_LARGE;
    let mut tmp = Canvas::new(f.cw(), f.height());
    tmp.draw_char(0, 0, ch, f, 0xFF);
    for yy in 0..tmp.h {
        for xx in 0..tmp.w {
            let a = tmp.buf[(yy * tmp.w + xx) as usize] & 0xFF;
            if a > 0 {
                c.blend_px(x + xx, y + yy, 0xFFFFFF, a * alpha / 255);
            }
        }
    }
}

/// The Foundation logo: a pediment over three columns on a stepped base.
pub fn draw_logo(c: &mut Canvas, x: i32, y: i32, size: i32, color: Color, alpha: u32) {
    let s = size;
    let part = |c: &mut Canvas, rx: i32, ry: i32, rw: i32, rh: i32| {
        if alpha >= 255 {
            c.fill_rect(x + rx, y + ry, rw.max(1), rh.max(1), color);
        } else {
            c.blend_rect(x + rx, y + ry, rw.max(1), rh.max(1), color, alpha);
        }
    };
    // Pediment (triangle) built from rows.
    let ph = s * 22 / 100;
    for dy in 0..ph {
        let hw = (s / 2) * dy / ph.max(1);
        part(c, s / 2 - hw, dy, 2 * hw + 1, 1);
    }
    part(c, 0, ph, s, s * 6 / 100);
    // Columns.
    let col_w = s * 14 / 100;
    let col_top = ph + s * 10 / 100;
    let col_h = s * 48 / 100;
    for i in 0..3 {
        let cx = s * 12 / 100 + i * (s * 31 / 100);
        part(c, cx, col_top, col_w, col_h);
    }
    // Base steps.
    let by = col_top + col_h + s * 3 / 100;
    part(c, s * 4 / 100, by, s - s * 8 / 100, s * 6 / 100);
    part(c, 0, by + s * 8 / 100, s, s * 6 / 100);
}

fn draw_window(c: &mut Canvas, w: &mut Window, focused: bool) {
    let r = w.rect;
    // Shadow.
    c.blend_round_rect(r.x + 6, r.y + 8, r.w, r.h, 10, 0x000000, if focused { 90 } else { 50 });
    // Frame.
    c.fill_round_rect(r.x, r.y, r.w, r.h, 8, if focused { 0x1A2238 } else { 0x2C3448 });
    // Title.
    c.set_clip(Rect::new(r.x, r.y, r.w - 56, TITLE_H));
    c.fill_round_rect(r.x + 10, r.y + 9, 12, 12, 3, w.app.kind().color());
    c.text(r.x + 30, r.y + 7, &w.app.title(), FONT_BOLD, if focused { 0xFFFFFF } else { 0xA8B2C8 });
    c.reset_clip();
    let cb = w.close_btn();
    let mb = w.min_btn();
    c.fill_circle(cb.x + 8, cb.y + 8, 7, if focused { 0xFF5F57 } else { 0x5A6378 });
    c.fill_circle(mb.x + 8, mb.y + 8, 7, if focused { 0xFEBC2E } else { 0x5A6378 });
    if focused {
        c.line(cb.x + 5, cb.y + 5, cb.x + 11, cb.y + 11, 1, 0x7A1F1A);
        c.line(cb.x + 11, cb.y + 5, cb.x + 5, cb.y + 11, 1, 0x7A1F1A);
        c.fill_rect(mb.x + 4, mb.y + 8, 9, 1, 0x7A5A10);
    }
    // Content.
    let content = w.content();
    c.set_clip(content);
    w.app.draw(c, content);
    c.reset_clip();
}

const CURSOR: [&[u8]; 19] = [
    b"X           ",
    b"XX          ",
    b"X.X         ",
    b"X..X        ",
    b"X...X       ",
    b"X....X      ",
    b"X.....X     ",
    b"X......X    ",
    b"X.......X   ",
    b"X........X  ",
    b"X.........X ",
    b"X......XXXXX",
    b"X...X..X    ",
    b"X..XX..X    ",
    b"X.X  X..X   ",
    b"XX   X..X   ",
    b"X     X..X  ",
    b"      X..X  ",
    b"       XX   ",
];

fn draw_cursor(c: &mut Canvas, x: i32, y: i32) {
    for (dy, row) in CURSOR.iter().enumerate() {
        for (dx, &p) in row.iter().enumerate() {
            match p {
                b'X' => c.put(x + dx as i32, y + dy as i32, 0x000000),
                b'.' => c.put(x + dx as i32, y + dy as i32, 0xFFFFFF),
                _ => {}
            }
        }
    }
}
