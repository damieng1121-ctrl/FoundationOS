//! Built-in Foundation applications.
use crate::fs;
use crate::gfx::*;
use crate::mathx::{cos, sin};
use crate::rtc;
use crate::sys::{self, Request};
use crate::wm::{draw_logo, ACCENT};
use alloc::boxed::Box;
use alloc::collections::VecDeque;
use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;
use core::f32::consts::PI;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Key {
    Char(char),
    Enter,
    Backspace,
    Tab,
    Esc,
    Up,
    Down,
    Left,
    Right,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AppKind {
    Terminal,
    Files,
    Notepad,
    Paint,
    Clock,
    Monitor,
    About,
}

pub const ALL: [AppKind; 7] =
    [AppKind::Terminal, AppKind::Files, AppKind::Notepad, AppKind::Paint, AppKind::Clock, AppKind::Monitor, AppKind::About];

impl AppKind {
    pub fn name(self) -> &'static str {
        match self {
            AppKind::Terminal => "Terminal",
            AppKind::Files => "Files",
            AppKind::Notepad => "Notepad",
            AppKind::Paint => "Paint",
            AppKind::Clock => "Clock",
            AppKind::Monitor => "Monitor",
            AppKind::About => "About",
        }
    }
    pub fn color(self) -> Color {
        match self {
            AppKind::Terminal => 0x2D3748,
            AppKind::Files => 0xF2A93B,
            AppKind::Notepad => 0x3FB37F,
            AppKind::Paint => 0xE0567A,
            AppKind::Clock => 0x7C5CFF,
            AppKind::Monitor => 0x18A0C9,
            AppKind::About => ACCENT,
        }
    }
    pub fn from_name(s: &str) -> Option<AppKind> {
        ALL.iter().copied().find(|k| k.name().eq_ignore_ascii_case(s))
    }
}

pub trait App {
    fn kind(&self) -> AppKind;
    fn title(&self) -> String {
        self.kind().name().to_string()
    }
    /// Initial content size.
    fn size(&self) -> (i32, i32);
    fn draw(&mut self, c: &mut Canvas, r: Rect);
    fn key(&mut self, _k: Key) {}
    fn mouse_down(&mut self, _x: i32, _y: i32) {}
    fn mouse_drag(&mut self, _x: i32, _y: i32) {}
    fn mouse_up(&mut self, _x: i32, _y: i32) {}
    /// Called ~10x/second. Return true to request a redraw.
    fn tick(&mut self) -> bool {
        false
    }
    fn closed(&self) -> bool {
        false
    }
}

pub fn create(kind: AppKind) -> Box<dyn App> {
    match kind {
        AppKind::Terminal => Box::new(Terminal::new()),
        AppKind::Files => Box::new(Files::new()),
        AppKind::Notepad => Box::new(Notepad::with_file("untitled.txt")),
        AppKind::Paint => Box::new(Paint::new()),
        AppKind::Clock => Box::new(Clock::new()),
        AppKind::Monitor => Box::new(Monitor::new()),
        AppKind::About => Box::new(About),
    }
}

/// 48x48 desktop icon.
pub fn draw_icon(c: &mut Canvas, kind: AppKind, x: i32, y: i32) {
    c.blend_round_rect(x + 2, y + 3, 48, 48, 12, 0x000000, 70);
    c.fill_round_rect(x, y, 48, 48, 12, kind.color());
    c.blend_round_rect(x, y, 48, 24, 12, 0xFFFFFF, 30);
    let w = 0xFFFFFF;
    match kind {
        AppKind::Terminal => {
            c.text(x + 9, y + 12, ">_", FONT_LARGE, 0x7EE787);
        }
        AppKind::Files => {
            c.fill_round_rect(x + 9, y + 13, 14, 6, 2, 0xFFF3D6);
            c.fill_round_rect(x + 9, y + 17, 30, 20, 3, 0xFFF3D6);
        }
        AppKind::Notepad => {
            c.fill_round_rect(x + 12, y + 9, 24, 30, 3, w);
            for i in 0..4 {
                c.fill_rect(x + 16, y + 15 + i * 6, 16, 2, 0x3FB37F);
            }
        }
        AppKind::Paint => {
            c.fill_circle(x + 24, y + 24, 14, w);
            c.fill_circle(x + 18, y + 19, 3, 0xE0567A);
            c.fill_circle(x + 27, y + 16, 3, 0x4F8CFF);
            c.fill_circle(x + 32, y + 24, 3, 0x3FB37F);
            c.fill_circle(x + 22, y + 30, 4, 0xE0567A);
        }
        AppKind::Clock => {
            c.fill_circle(x + 24, y + 24, 15, w);
            c.line(x + 24, y + 24, x + 24, y + 13, 3, 0x2D2D2D);
            c.line(x + 24, y + 24, x + 32, y + 28, 3, 0x2D2D2D);
        }
        AppKind::Monitor => {
            let bars = [10, 18, 14, 24, 20];
            for (i, h) in bars.iter().enumerate() {
                c.fill_rect(x + 10 + i as i32 * 6, y + 38 - h, 4, *h, w);
            }
        }
        AppKind::About => {
            draw_logo(c, x + 10, y + 9, 28, w, 255);
        }
    }
}

fn wrap(s: &str, cols: usize) -> Vec<String> {
    let mut out = Vec::new();
    for line in s.split('\n') {
        let chars: Vec<char> = line.chars().collect();
        if chars.is_empty() {
            out.push(String::new());
        }
        for chunk in chars.chunks(cols.max(1)) {
            out.push(chunk.iter().collect());
        }
    }
    out
}

fn button(c: &mut Canvas, r: Rect, label: &str, bg: Color) {
    c.fill_round_rect(r.x, r.y, r.w, r.h, 6, bg);
    c.text_centered(r, label, FONT, 0xFFFFFF);
}

fn blink() -> bool {
    (sys::uptime_ms() / 500) % 2 == 0
}

// =================================================================== Terminal

const PROMPT: &str = "foundation:/$ ";
const T_FG: Color = 0xD6DEEB;
const T_GREEN: Color = 0x7EE787;
const T_BLUE: Color = 0x79C0FF;
const T_RED: Color = 0xFF7B72;
const T_YELLOW: Color = 0xE3B341;

pub struct Terminal {
    lines: Vec<(String, Color)>,
    input: String,
    history: Vec<String>,
    hist_pos: usize,
    blink: bool,
    exit: bool,
}

impl Terminal {
    pub fn new() -> Self {
        let mut t = Self { lines: Vec::new(), input: String::new(), history: Vec::new(), hist_pos: 0, blink: true, exit: false };
        t.out("Foundation OS 0.1 - Rust x86_64 kernel", T_BLUE);
        t.out("Type 'help' for a list of commands.", T_FG);
        t.out("", T_FG);
        t
    }

    fn out(&mut self, s: &str, c: Color) {
        for l in s.split('\n') {
            self.lines.push((l.to_string(), c));
        }
        if self.lines.len() > 500 {
            self.lines.drain(0..100);
        }
    }

    fn run(&mut self, line: &str) {
        self.lines.push((format!("{}{}", PROMPT, line), T_GREEN));
        let line = line.trim();
        if line.is_empty() {
            return;
        }
        self.history.push(line.to_string());
        self.hist_pos = self.history.len();
        let (cmd, rest) = match line.find(' ') {
            Some(i) => (&line[..i], line[i + 1..].trim()),
            None => (line, ""),
        };
        match cmd {
            "help" => self.out(
                "Commands:\n  help              this list\n  clear             clear the screen\n  echo <text>       print text\n  \
ls                list files\n  cat <file>        show a file\n  write <file> <t>  write text to a file\n  \
rm <file>         delete a file\n  edit <file>       open a file in Notepad\n  open <app>        launch an app\n  \
apps              list apps\n  ps                list open windows\n  uptime | date    time info\n  \
mem               memory usage\n  cpu               processor info\n  calc <a> <op> <b> integer maths\n  \
neofetch          system summary\n  dmesg             kernel log\n  reboot | shutdown power\n  exit              close terminal",
                T_FG,
            ),
            "clear" => self.lines.clear(),
            "echo" => self.out(rest, T_FG),
            "ls" => {
                let files = fs::list();
                if files.is_empty() {
                    self.out("(no files)", T_FG);
                }
                for (n, sz) in files {
                    self.out(&format!("  {:<24} {:>6} B", n, sz), T_BLUE);
                }
            }
            "cat" => match fs::read(rest) {
                Some(s) => self.out(&s, T_FG),
                None => self.out(&format!("cat: {}: no such file", rest), T_RED),
            },
            "write" => match rest.find(' ') {
                Some(i) => {
                    fs::write(&rest[..i], &rest[i + 1..]);
                    self.out(&format!("wrote {} bytes to {}", rest.len() - i - 1, &rest[..i]), T_FG);
                }
                None => self.out("usage: write <file> <text>", T_YELLOW),
            },
            "rm" => {
                if fs::remove(rest) {
                    self.out(&format!("removed {}", rest), T_FG)
                } else {
                    self.out(&format!("rm: {}: no such file", rest), T_RED)
                }
            }
            "edit" if !rest.is_empty() => sys::request(Request::Edit(rest.to_string())),
            "open" => match AppKind::from_name(rest) {
                Some(k) => sys::request(Request::Open(k)),
                None => self.out("open: unknown app (try 'apps')", T_RED),
            },
            "apps" => {
                let names: Vec<&str> = ALL.iter().map(|k| k.name()).collect();
                self.out(&names.join("  "), T_BLUE);
            }
            "ps" => {
                let wins = sys::WINDOWS.lock().clone();
                for (i, w) in wins.iter().enumerate() {
                    self.out(&format!("  {:>3}  {}", i + 1, w), T_FG);
                }
            }
            "uptime" => self.out(&format!("up {}", sys::uptime_string()), T_FG),
            "date" => {
                let t = rtc::now();
                self.out(
                    &format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02} (RTC)", t.year, t.month, t.day, t.hour, t.minute, t.second),
                    T_FG,
                );
            }
            "mem" => {
                let (used, size) = crate::allocator::stats();
                let phys = sys::PHYS_USABLE.load(core::sync::atomic::Ordering::Relaxed);
                self.out(
                    &format!(
                        "heap:     {} used / {}\nphysical: {} usable",
                        sys::human_bytes(used as u64),
                        sys::human_bytes(size as u64),
                        sys::human_bytes(phys)
                    ),
                    T_FG,
                );
            }
            "cpu" => self.out(sys::cpu_brand(), T_FG),
            "calc" => {
                let p: Vec<&str> = rest.split_whitespace().collect();
                let res = if p.len() == 3 {
                    match (p[0].parse::<i64>(), p[2].parse::<i64>()) {
                        (Ok(a), Ok(b)) => match p[1] {
                            "+" => Some(a.wrapping_add(b)),
                            "-" => Some(a.wrapping_sub(b)),
                            "*" | "x" => Some(a.wrapping_mul(b)),
                            "/" if b != 0 => Some(a / b),
                            "%" if b != 0 => Some(a % b),
                            _ => None,
                        },
                        _ => None,
                    }
                } else {
                    None
                };
                match res {
                    Some(v) => self.out(&format!("{}", v), T_FG),
                    None => self.out("usage: calc <a> <+|-|*|/|%> <b>", T_YELLOW),
                }
            }
            "neofetch" | "about" => {
                let (used, size) = crate::allocator::stats();
                let w = sys::SCREEN_W.load(core::sync::atomic::Ordering::Relaxed);
                let h = sys::SCREEN_H.load(core::sync::atomic::Ordering::Relaxed);
                self.out("     /\\        foundation@foundation", T_BLUE);
                self.out("    /  \\       ---------------------", T_BLUE);
                self.out(&format!("   /____\\      OS:      Foundation 0.1 x86_64"), T_BLUE);
                self.out(&format!("   | || |      Kernel:  foundation (Rust, no_std)"), T_BLUE);
                self.out(&format!("   | || |      Uptime:  {}", sys::uptime_string()), T_BLUE);
                self.out(&format!("  _|_||_|_     Display: {}x{}", w, h), T_BLUE);
                self.out(&format!(" |________|    CPU:     {}", sys::cpu_brand()), T_BLUE);
                self.out(
                    &format!("               Memory:  {} / {}", sys::human_bytes(used as u64), sys::human_bytes(size as u64)),
                    T_BLUE,
                );
            }
            "dmesg" => {
                for l in sys::log_lines() {
                    self.out(&l, T_FG);
                }
            }
            "reboot" => sys::reboot(),
            "shutdown" | "poweroff" => sys::shutdown(),
            "exit" => self.exit = true,
            _ => self.out(&format!("{}: command not found", cmd), T_RED),
        }
    }
}

impl App for Terminal {
    fn kind(&self) -> AppKind {
        AppKind::Terminal
    }
    fn size(&self) -> (i32, i32) {
        (680, 420)
    }
    fn key(&mut self, k: Key) {
        match k {
            Key::Char(ch) if !ch.is_control() => self.input.push(ch),
            Key::Backspace => {
                self.input.pop();
            }
            Key::Enter => {
                let l = core::mem::take(&mut self.input);
                self.run(&l);
            }
            Key::Up if self.hist_pos > 0 => {
                self.hist_pos -= 1;
                self.input = self.history[self.hist_pos].clone();
            }
            Key::Down if self.hist_pos < self.history.len() => {
                self.hist_pos += 1;
                self.input = self.history.get(self.hist_pos).cloned().unwrap_or_default();
            }
            _ => {}
        }
    }
    fn tick(&mut self) -> bool {
        let b = blink();
        let changed = b != self.blink;
        self.blink = b;
        changed
    }
    fn closed(&self) -> bool {
        self.exit
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        c.fill_rect(r.x, r.y, r.w, r.h, 0x0D1117);
        let f = FONT;
        let lh = 18;
        let cols = ((r.w - 16) / f.cw()).max(1) as usize;
        let rows = ((r.h - 12) / lh).max(1) as usize;
        let mut vis: Vec<(String, Color)> = Vec::new();
        for (l, col) in &self.lines {
            for w in wrap(l, cols) {
                vis.push((w, *col));
            }
        }
        let input_line = format!("{}{}", PROMPT, self.input);
        let input_wrapped = wrap(&input_line, cols);
        let n_in = input_wrapped.len();
        for w in input_wrapped {
            vis.push((w, T_FG));
        }
        let start = vis.len().saturating_sub(rows);
        let mut y = r.y + 6;
        for (i, (l, col)) in vis[start..].iter().enumerate() {
            let is_input = start + i >= vis.len() - n_in;
            if is_input && start + i == vis.len() - n_in && l.starts_with(PROMPT) {
                let pw = c.text(r.x + 8, y, PROMPT, f, T_GREEN);
                c.text(r.x + 8 + pw, y, &l[PROMPT.len()..], f, T_FG);
            } else {
                c.text(r.x + 8, y, l, f, *col);
            }
            y += lh;
        }
        if self.blink {
            let last = &vis[vis.len() - 1].0;
            let cx = r.x + 8 + last.chars().count() as i32 * f.cw();
            c.fill_rect(cx, y - lh + 1, f.cw(), 16, 0xC9D1D9);
        }
    }
}

// ====================================================================== Clock

pub struct Clock {
    last: u8,
}

impl Clock {
    pub fn new() -> Self {
        Self { last: 255 }
    }
}

impl App for Clock {
    fn kind(&self) -> AppKind {
        AppKind::Clock
    }
    fn size(&self) -> (i32, i32) {
        (300, 340)
    }
    fn tick(&mut self) -> bool {
        let s = rtc::now().second;
        let ch = s != self.last;
        self.last = s;
        ch
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        c.gradient_v(r.x, r.y, r.w, r.h, 0x221A44, 0x120E26);
        let t = rtc::now();
        let rad = ((r.w.min(r.h - 80)) / 2 - 16).max(30);
        let cx = r.x + r.w / 2;
        let cy = r.y + 16 + rad;
        c.fill_circle(cx, cy + 3, rad + 4, 0x0A0818);
        c.fill_circle(cx, cy, rad + 4, 0x7C5CFF);
        c.fill_circle(cx, cy, rad, 0xF7F5FF);
        for i in 0..60 {
            let a = i as f32 * PI / 30.0;
            let (s, co) = (sin(a), cos(a));
            let len = if i % 5 == 0 { 12.0 } else { 5.0 };
            let r0 = rad as f32 - 6.0;
            let r1 = r0 - len;
            c.line(
                cx + (s * r0) as i32,
                cy - (co * r0) as i32,
                cx + (s * r1) as i32,
                cy - (co * r1) as i32,
                if i % 5 == 0 { 3 } else { 1 },
                if i % 5 == 0 { 0x2A2250 } else { 0x9A94B8 },
            );
        }
        let hand = |c: &mut Canvas, a: f32, len: f32, th: i32, col: Color| {
            c.line(cx, cy, cx + (sin(a) * len) as i32, cy - (cos(a) * len) as i32, th, col);
        };
        let sec = t.second as f32;
        let min = t.minute as f32 + sec / 60.0;
        let hr = (t.hour % 12) as f32 + min / 60.0;
        let rf = rad as f32;
        hand(c, hr * PI / 6.0, rf * 0.5, 6, 0x1E1838);
        hand(c, min * PI / 30.0, rf * 0.72, 4, 0x1E1838);
        hand(c, sec * PI / 30.0, rf * 0.8, 2, 0xE0567A);
        c.fill_circle(cx, cy, 5, 0xE0567A);
        let time = format!("{:02}:{:02}:{:02}", t.hour, t.minute, t.second);
        let date = format!("{} {} {}", t.day, rtc::MONTHS[(t.month.max(1) as usize - 1) % 12], t.year);
        let ty = cy + rad + 14;
        c.text_centered(Rect::new(r.x, ty, r.w, 26), &time, FONT_LARGE, 0xFFFFFF);
        c.text_centered(Rect::new(r.x, ty + 26, r.w, 20), &date, FONT, 0xB8B0E0);
    }
}

// ==================================================================== Monitor

pub struct Monitor {
    history: VecDeque<u32>,
    last_sample: u64,
}

impl Monitor {
    pub fn new() -> Self {
        Self { history: VecDeque::new(), last_sample: 0 }
    }
}

impl App for Monitor {
    fn kind(&self) -> AppKind {
        AppKind::Monitor
    }
    fn title(&self) -> String {
        "System Monitor".into()
    }
    fn size(&self) -> (i32, i32) {
        (440, 400)
    }
    fn tick(&mut self) -> bool {
        let now = sys::uptime_ms();
        if now - self.last_sample >= 500 || self.history.is_empty() {
            self.last_sample = now;
            let (u, s) = crate::allocator::stats();
            self.history.push_back((u as u64 * 1000 / s.max(1) as u64) as u32);
            if self.history.len() > 80 {
                self.history.pop_front();
            }
            return true;
        }
        false
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        use core::sync::atomic::Ordering::Relaxed;
        c.fill_rect(r.x, r.y, r.w, r.h, 0xF4F6FB);
        let x = r.x + 18;
        let mut y = r.y + 14;
        c.text(x, y, "System", FONT_MED, 0x1A2238);
        y += 30;
        let rows = [
            ("CPU", String::from(sys::cpu_brand())),
            ("Uptime", sys::uptime_string()),
            ("Display", format!("{} x {}", sys::SCREEN_W.load(Relaxed), sys::SCREEN_H.load(Relaxed))),
            ("Timer ticks", format!("{} @ 100 Hz", sys::ticks())),
            ("Frames drawn", format!("{}", sys::FRAMES_DRAWN.load(Relaxed))),
            ("Windows", format!("{}", sys::WINDOWS.lock().len())),
            ("Physical RAM", sys::human_bytes(sys::PHYS_USABLE.load(Relaxed))),
        ];
        c.set_clip(r);
        for (k, v) in rows.iter() {
            c.text(x, y, k, FONT_BOLD, 0x4A5470);
            c.text(x + 130, y, v, FONT, 0x1A2238);
            y += 22;
        }
        y += 8;
        let (used, size) = crate::allocator::stats();
        c.text(x, y, "Kernel heap", FONT_BOLD, 0x4A5470);
        let lbl = format!("{} / {}", sys::human_bytes(used as u64), sys::human_bytes(size as u64));
        c.text(x + 130, y, &lbl, FONT, 0x1A2238);
        y += 24;
        let bw = r.w - 36;
        c.fill_round_rect(x, y, bw, 12, 6, 0xDDE3EF);
        let fill = ((used as i64 * bw as i64) / size.max(1) as i64).max(6) as i32;
        c.fill_round_rect(x, y, fill, 12, 6, 0x18A0C9);
        y += 24;
        // Graph.
        let gh = (r.y + r.h - y - 16).max(30);
        c.fill_round_rect(x, y, bw, gh, 6, 0xFFFFFF);
        c.rect(x, y, bw, gh, 0xDDE3EF);
        let n = self.history.len();
        if n > 1 {
            let max = (*self.history.iter().max().unwrap()).max(1) * 5 / 4;
            let step = bw as f32 / 79.0;
            let pts: Vec<(i32, i32)> = self
                .history
                .iter()
                .enumerate()
                .map(|(i, v)| {
                    let px = x + bw - ((n - 1 - i) as f32 * step) as i32 - 1;
                    let py = y + gh - 4 - (*v as i32 * (gh - 8) / max as i32);
                    (px, py)
                })
                .collect();
            for p in pts.windows(2) {
                c.line(p[0].0, p[0].1, p[1].0, p[1].1, 2, 0x18A0C9);
            }
        }
        c.text(x + 8, y + 6, "heap usage", FONT, 0x8A93AA);
        c.reset_clip();
    }
}

// ====================================================================== Paint

const PALETTE: [Color; 10] =
    [0x111111, 0xFFFFFF, 0xE0567A, 0xF2A93B, 0xF5D547, 0x3FB37F, 0x18A0C9, 0x4F8CFF, 0x7C5CFF, 0x8B5A2B];
const PAINT_BAR: i32 = 40;

pub struct Paint {
    art: Option<Canvas>,
    color: Color,
    brush: i32,
    last: Option<(i32, i32)>,
    width: i32,
}

impl Paint {
    pub fn new() -> Self {
        Self { art: None, color: 0xE0567A, brush: 4, last: None, width: 600 }
    }
    fn swatch(i: usize) -> Rect {
        Rect::new(8 + i as i32 * 28, 8, 24, 24)
    }
    fn brush_btn(&self, i: usize) -> Rect {
        Rect::new(8 + 10 * 28 + 12 + i as i32 * 30, 8, 26, 24)
    }
    fn clear_btn(&self) -> Rect {
        Rect::new(self.width - 70, 8, 62, 24)
    }
    fn paint_to(&mut self, x: i32, y: i32) {
        let (brush, color, last) = (self.brush, self.color, self.last);
        if let Some(a) = self.art.as_mut() {
            let (ax, ay) = (x, y - PAINT_BAR);
            match last {
                Some((lx, ly)) => a.line(lx, ly, ax, ay, brush, color),
                None => a.fill_circle(ax, ay, brush / 2, color),
            }
            self.last = Some((ax, ay));
        }
    }
}

impl App for Paint {
    fn kind(&self) -> AppKind {
        AppKind::Paint
    }
    fn size(&self) -> (i32, i32) {
        (600, 440)
    }
    fn mouse_down(&mut self, x: i32, y: i32) {
        if y < PAINT_BAR {
            for (i, col) in PALETTE.iter().enumerate() {
                if Self::swatch(i).contains(x, y) {
                    self.color = *col;
                }
            }
            for (i, b) in [2, 4, 10].iter().enumerate() {
                if self.brush_btn(i).contains(x, y) {
                    self.brush = *b;
                }
            }
            if self.clear_btn().contains(x, y) {
                if let Some(a) = self.art.as_mut() {
                    a.fill_rect(0, 0, a.w, a.h, 0xFFFFFF);
                }
            }
            return;
        }
        self.last = None;
        self.paint_to(x, y);
    }
    fn mouse_drag(&mut self, x: i32, y: i32) {
        if self.last.is_some() {
            self.paint_to(x, y);
        }
    }
    fn mouse_up(&mut self, _x: i32, _y: i32) {
        self.last = None;
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        self.width = r.w;
        let (aw, ah) = (r.w, r.h - PAINT_BAR);
        if self.art.as_ref().map(|a| a.w != aw || a.h != ah).unwrap_or(true) {
            let mut a = Canvas::new(aw.max(1), ah.max(1));
            a.fill_rect(0, 0, aw, ah, 0xFFFFFF);
            if let Some(old) = &self.art {
                a.blit(old, 0, 0);
            }
            self.art = Some(a);
        }
        c.fill_rect(r.x, r.y, r.w, PAINT_BAR, 0xECEFF5);
        c.fill_rect(r.x, r.y + PAINT_BAR - 1, r.w, 1, 0xD0D6E2);
        for (i, col) in PALETTE.iter().enumerate() {
            let s = Self::swatch(i);
            if *col == self.color {
                c.fill_round_rect(r.x + s.x - 3, r.y + s.y - 3, s.w + 6, s.h + 6, 7, 0x1A2238);
            }
            c.fill_round_rect(r.x + s.x, r.y + s.y, s.w, s.h, 5, *col);
            if *col == 0xFFFFFF {
                c.rect(r.x + s.x, r.y + s.y, s.w, s.h, 0xC0C6D2);
            }
        }
        for (i, b) in [2, 4, 10].iter().enumerate() {
            let s = self.brush_btn(i);
            let bg = if *b == self.brush { 0xC9D3EA } else { 0xFFFFFF };
            c.fill_round_rect(r.x + s.x, r.y + s.y, s.w, s.h, 5, bg);
            c.fill_circle(r.x + s.x + s.w / 2, r.y + s.y + s.h / 2, (*b / 2).max(1), 0x1A2238);
        }
        let cb = self.clear_btn();
        button(c, Rect::new(r.x + cb.x, r.y + cb.y, cb.w, cb.h), "Clear", 0x8C2F39);
        if let Some(a) = &self.art {
            c.blit(a, r.x, r.y + PAINT_BAR);
        }
    }
}

// ==================================================================== Notepad

pub struct Notepad {
    file: String,
    text: String,
    status: String,
    blink: bool,
    width: i32,
}

impl Notepad {
    pub fn with_file(name: &str) -> Self {
        let text = fs::read(name).unwrap_or_default();
        Self { file: name.to_string(), text, status: String::new(), blink: true, width: 520 }
    }
    fn save_btn(&self) -> Rect {
        Rect::new(self.width - 76, 6, 68, 26)
    }
}

impl App for Notepad {
    fn kind(&self) -> AppKind {
        AppKind::Notepad
    }
    fn title(&self) -> String {
        format!("{} - Notepad", self.file)
    }
    fn size(&self) -> (i32, i32) {
        (540, 400)
    }
    fn key(&mut self, k: Key) {
        match k {
            Key::Char(ch) if !ch.is_control() => self.text.push(ch),
            Key::Enter => self.text.push('\n'),
            Key::Tab => self.text.push_str("    "),
            Key::Backspace => {
                self.text.pop();
            }
            _ => return,
        }
        self.status.clear();
    }
    fn mouse_down(&mut self, x: i32, y: i32) {
        if self.save_btn().contains(x, y) {
            fs::write(&self.file, &self.text);
            self.status = format!("Saved {} bytes", self.text.len());
        }
    }
    fn tick(&mut self) -> bool {
        let b = blink();
        let ch = b != self.blink;
        self.blink = b;
        ch
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        self.width = r.w;
        c.fill_rect(r.x, r.y, r.w, r.h, 0xFFFFFF);
        c.fill_rect(r.x, r.y, r.w, 38, 0xEEF6F1);
        c.fill_rect(r.x, r.y + 38, r.w, 1, 0xCFE3D7);
        c.text(r.x + 12, r.y + 11, &self.file, FONT_BOLD, 0x1F5C40);
        if !self.status.is_empty() {
            let fw = text_width(&self.file, FONT_BOLD);
            c.text(r.x + 24 + fw, r.y + 11, &self.status, FONT, 0x3FB37F);
        }
        let sb = self.save_btn();
        button(c, Rect::new(r.x + sb.x, r.y + sb.y, sb.w, sb.h), "Save", 0x3FB37F);
        let cols = ((r.w - 24) / FONT.cw()).max(1) as usize;
        let lines = wrap(&self.text, cols);
        let rows = ((r.h - 52) / 20).max(1) as usize;
        let start = lines.len().saturating_sub(rows);
        let mut y = r.y + 48;
        for l in &lines[start..] {
            c.text(r.x + 12, y, l, FONT, 0x1A2238);
            y += 20;
        }
        if self.blink {
            let last = lines.last().map(|l| l.chars().count()).unwrap_or(0) as i32;
            c.fill_rect(r.x + 12 + last * FONT.cw(), y - 20, 2, 17, 0x1A2238);
        }
    }
}

// ====================================================================== Files

pub struct Files {
    selected: Option<String>,
    width: i32,
    hover_new: bool,
}

impl Files {
    pub fn new() -> Self {
        Self { selected: None, width: 420, hover_new: false }
    }
    fn new_btn(&self) -> Rect {
        Rect::new(self.width - 96, 6, 88, 26)
    }
}

impl App for Files {
    fn kind(&self) -> AppKind {
        AppKind::Files
    }
    fn size(&self) -> (i32, i32) {
        (440, 330)
    }
    fn tick(&mut self) -> bool {
        true // directory contents may change from the terminal
    }
    fn mouse_down(&mut self, x: i32, y: i32) {
        if self.new_btn().contains(x, y) {
            let mut n = 1;
            while fs::exists(&format!("new-{}.txt", n)) {
                n += 1;
            }
            let name = format!("new-{}.txt", n);
            fs::write(&name, "");
            sys::request(Request::Edit(name));
            return;
        }
        if y >= 64 {
            let i = ((y - 64) / 30) as usize;
            if let Some((name, _)) = fs::list().get(i) {
                if self.selected.as_deref() == Some(name.as_str()) {
                    sys::request(Request::Edit(name.clone()));
                }
                self.selected = Some(name.clone());
            }
        }
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        self.width = r.w;
        let _ = self.hover_new;
        c.fill_rect(r.x, r.y, r.w, r.h, 0xFFFFFF);
        c.fill_rect(r.x, r.y, r.w, 38, 0xFFF6E6);
        c.fill_rect(r.x, r.y + 38, r.w, 1, 0xF0DDB8);
        c.text(r.x + 12, r.y + 11, "/  (FoundationFS, in memory)", FONT_BOLD, 0x7A4E0E);
        let nb = self.new_btn();
        button(c, Rect::new(r.x + nb.x, r.y + nb.y, nb.w, nb.h), "New file", 0xF2A93B);
        c.text(r.x + 46, r.y + 44, "Name", FONT, 0x8A93AA);
        c.text(r.x + r.w - 90, r.y + 44, "Size", FONT, 0x8A93AA);
        let mut y = r.y + 64;
        for (name, size) in fs::list() {
            if self.selected.as_deref() == Some(name.as_str()) {
                c.fill_rect(r.x, y, r.w, 30, 0xFFEBC7);
            }
            c.fill_round_rect(r.x + 14, y + 5, 18, 20, 3, 0xF2A93B);
            c.fill_rect(r.x + 18, y + 11, 10, 2, 0xFFFFFF);
            c.fill_rect(r.x + 18, y + 16, 10, 2, 0xFFFFFF);
            c.text(r.x + 46, y + 7, &name, FONT, 0x1A2238);
            c.text(r.x + r.w - 90, y + 7, &format!("{} B", size), FONT, 0x4A5470);
            y += 30;
        }
        c.text(r.x + 12, r.y + r.h - 22, "Double-click a file to open it.", FONT, 0x8A93AA);
    }
}

// ====================================================================== About

pub struct About;

impl App for About {
    fn kind(&self) -> AppKind {
        AppKind::About
    }
    fn title(&self) -> String {
        "About Foundation".into()
    }
    fn size(&self) -> (i32, i32) {
        (440, 320)
    }
    fn draw(&mut self, c: &mut Canvas, r: Rect) {
        c.gradient_v(r.x, r.y, r.w, 120, 0x1E3A7A, 0x4F3F9C);
        c.fill_rect(r.x, r.y + 120, r.w, r.h - 120, 0xFFFFFF);
        draw_logo(c, r.x + 24, r.y + 22, 76, 0xFFFFFF, 255);
        c.text(r.x + 124, r.y + 34, "Foundation OS", FONT_LARGE, 0xFFFFFF);
        c.text(r.x + 124, r.y + 66, "Version 0.1 \"Bedrock\"", FONT, 0xD0D8F5);
        let lines = [
            "A hobby operating system built from scratch",
            "in Rust for x86_64.",
            "",
            "Kernel: GDT/TSS, IDT, PIC + PIT, 4-level paging,",
            "        heap allocator, PS/2 keyboard & mouse, RTC",
            "Shell:  compositing window manager, taskbar,",
            "        start menu and built-in apps",
        ];
        let mut y = r.y + 136;
        for l in lines {
            c.text(r.x + 24, y, l, FONT, 0x2A3350);
            y += 20;
        }
    }
}
