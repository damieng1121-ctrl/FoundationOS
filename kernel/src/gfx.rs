//! 2D graphics: an off-screen canvas with clipping, primitives, anti-aliased text,
//! and presentation to the hardware framebuffer.
use crate::mathx::isqrt;
use alloc::vec;
use alloc::vec::Vec;
use bootloader_api::info::{FrameBufferInfo, PixelFormat};
use noto_sans_mono_bitmap::{get_raster, get_raster_width, FontWeight, RasterHeight};

pub type Color = u32; // 0xRRGGBB

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl Rect {
    pub const fn new(x: i32, y: i32, w: i32, h: i32) -> Self {
        Self { x, y, w, h }
    }
    pub fn contains(&self, px: i32, py: i32) -> bool {
        px >= self.x && py >= self.y && px < self.x + self.w && py < self.y + self.h
    }
    pub fn intersect(&self, o: &Rect) -> Rect {
        let x0 = self.x.max(o.x);
        let y0 = self.y.max(o.y);
        let x1 = (self.x + self.w).min(o.x + o.w);
        let y1 = (self.y + self.h).min(o.y + o.h);
        Rect::new(x0, y0, (x1 - x0).max(0), (y1 - y0).max(0))
    }
    pub fn inset(&self, d: i32) -> Rect {
        Rect::new(self.x + d, self.y + d, self.w - 2 * d, self.h - 2 * d)
    }
}

#[derive(Clone, Copy)]
pub struct Font {
    weight: FontWeight,
    size: RasterHeight,
}

impl Font {
    pub const fn cw(&self) -> i32 {
        get_raster_width(self.weight, self.size) as i32
    }
    pub const fn height(&self) -> i32 {
        self.size.val() as i32
    }
}

pub const FONT: Font = Font { weight: FontWeight::Regular, size: RasterHeight::Size16 };
pub const FONT_BOLD: Font = Font { weight: FontWeight::Bold, size: RasterHeight::Size16 };
pub const FONT_MED: Font = Font { weight: FontWeight::Bold, size: RasterHeight::Size20 };
pub const FONT_LARGE: Font = Font { weight: FontWeight::Bold, size: RasterHeight::Size24 };

#[inline]
pub fn blend(dst: Color, src: Color, a: u32) -> Color {
    let ia = 255 - a;
    let r = (((src >> 16) & 0xFF) * a + ((dst >> 16) & 0xFF) * ia) / 255;
    let g = (((src >> 8) & 0xFF) * a + ((dst >> 8) & 0xFF) * ia) / 255;
    let b = ((src & 0xFF) * a + (dst & 0xFF) * ia) / 255;
    (r << 16) | (g << 8) | b
}

pub fn lerp(c1: Color, c2: Color, t: u32) -> Color {
    blend(c1, c2, t.min(255))
}

pub struct Canvas {
    pub w: i32,
    pub h: i32,
    pub buf: Vec<u32>,
    clip: Rect,
}

impl Canvas {
    pub fn new(w: i32, h: i32) -> Self {
        Self { w, h, buf: vec![0; (w * h) as usize], clip: Rect::new(0, 0, w, h) }
    }

    pub fn set_clip(&mut self, r: Rect) {
        self.clip = r.intersect(&Rect::new(0, 0, self.w, self.h));
    }
    pub fn reset_clip(&mut self) {
        self.clip = Rect::new(0, 0, self.w, self.h);
    }

    #[inline]
    pub fn put(&mut self, x: i32, y: i32, c: Color) {
        if self.clip.contains(x, y) {
            self.buf[(y * self.w + x) as usize] = c;
        }
    }

    #[inline]
    pub fn blend_px(&mut self, x: i32, y: i32, c: Color, a: u32) {
        if self.clip.contains(x, y) {
            let i = (y * self.w + x) as usize;
            self.buf[i] = blend(self.buf[i], c, a);
        }
    }

    pub fn fill_rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: Color) {
        let r = Rect::new(x, y, w, h).intersect(&self.clip);
        for yy in r.y..r.y + r.h {
            let s = (yy * self.w + r.x) as usize;
            self.buf[s..s + r.w as usize].fill(c);
        }
    }

    pub fn blend_rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: Color, a: u32) {
        let r = Rect::new(x, y, w, h).intersect(&self.clip);
        for yy in r.y..r.y + r.h {
            let s = (yy * self.w + r.x) as usize;
            for p in &mut self.buf[s..s + r.w as usize] {
                *p = blend(*p, c, a);
            }
        }
    }

    pub fn rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: Color) {
        self.fill_rect(x, y, w, 1, c);
        self.fill_rect(x, y + h - 1, w, 1, c);
        self.fill_rect(x, y, 1, h, c);
        self.fill_rect(x + w - 1, y, 1, h, c);
    }

    pub fn gradient_v(&mut self, x: i32, y: i32, w: i32, h: i32, c1: Color, c2: Color) {
        for i in 0..h {
            let c = lerp(c1, c2, (i * 255 / h.max(1)) as u32);
            self.fill_rect(x, y + i, w, 1, c);
        }
    }

    fn round_inset(r: i32, h: i32, dy: i32) -> i32 {
        let d = if dy < r {
            r - dy
        } else if dy >= h - r {
            dy - (h - r) + 1
        } else {
            return 0;
        };
        r - isqrt(r * r - d * d)
    }

    pub fn fill_round_rect(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, c: Color) {
        let r = r.min(w / 2).min(h / 2);
        for dy in 0..h {
            let ins = Self::round_inset(r, h, dy);
            self.fill_rect(x + ins, y + dy, w - 2 * ins, 1, c);
        }
    }

    pub fn blend_round_rect(&mut self, x: i32, y: i32, w: i32, h: i32, r: i32, c: Color, a: u32) {
        let r = r.min(w / 2).min(h / 2);
        for dy in 0..h {
            let ins = Self::round_inset(r, h, dy);
            self.blend_rect(x + ins, y + dy, w - 2 * ins, 1, c, a);
        }
    }

    pub fn fill_circle(&mut self, cx: i32, cy: i32, r: i32, c: Color) {
        for dy in -r..=r {
            let dx = isqrt(r * r - dy * dy);
            self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, c);
        }
    }

    pub fn line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, thick: i32, c: Color) {
        let (mut x, mut y) = (x0, y0);
        let dx = (x1 - x0).abs();
        let dy = -(y1 - y0).abs();
        let sx = if x0 < x1 { 1 } else { -1 };
        let sy = if y0 < y1 { 1 } else { -1 };
        let mut err = dx + dy;
        let t = thick.max(1);
        loop {
            if t == 1 {
                self.put(x, y, c);
            } else {
                self.fill_circle(x, y, t / 2, c);
            }
            if x == x1 && y == y1 {
                break;
            }
            let e2 = 2 * err;
            if e2 >= dy {
                err += dy;
                x += sx;
            }
            if e2 <= dx {
                err += dx;
                y += sy;
            }
        }
    }


    pub fn draw_char(&mut self, x: i32, y: i32, ch: char, f: Font, c: Color) -> i32 {
        let r = get_raster(ch, f.weight, f.size).or_else(|| get_raster('?', f.weight, f.size));
        if let Some(r) = r {
            for (dy, row) in r.raster().iter().enumerate() {
                for (dx, &a) in row.iter().enumerate() {
                    if a > 8 {
                        self.blend_px(x + dx as i32, y + dy as i32, c, a as u32);
                    }
                }
            }
        }
        f.cw()
    }

    pub fn text(&mut self, x: i32, y: i32, s: &str, f: Font, c: Color) -> i32 {
        let mut cx = x;
        for ch in s.chars() {
            cx += self.draw_char(cx, y, ch, f, c);
        }
        cx - x
    }

    pub fn text_centered(&mut self, r: Rect, s: &str, f: Font, c: Color) {
        let w = text_width(s, f);
        self.text(r.x + (r.w - w) / 2, r.y + (r.h - f.height()) / 2, s, f, c);
    }

    /// Copy another canvas onto this one at (x, y), honouring the clip.
    pub fn blit(&mut self, src: &Canvas, x: i32, y: i32) {
        let r = Rect::new(x, y, src.w, src.h).intersect(&self.clip);
        for yy in r.y..r.y + r.h {
            let sy = yy - y;
            let sx = r.x - x;
            let s = (sy * src.w + sx) as usize;
            let d = (yy * self.w + r.x) as usize;
            self.buf[d..d + r.w as usize].copy_from_slice(&src.buf[s..s + r.w as usize]);
        }
    }
}

pub fn text_width(s: &str, f: Font) -> i32 {
    s.chars().count() as i32 * f.cw()
}

/// The physical framebuffer handed to us by the bootloader.
pub struct Screen {
    fb: &'static mut [u8],
    info: FrameBufferInfo,
}

impl Screen {
    pub fn new(fb: &'static mut [u8], info: FrameBufferInfo) -> Self {
        Self { fb, info }
    }

    pub fn present(&mut self, c: &Canvas) {
        let info = self.info;
        let bpp = info.bytes_per_pixel;
        let w = (c.w as usize).min(info.width);
        let h = (c.h as usize).min(info.height);
        for y in 0..h {
            let src = &c.buf[y * c.w as usize..y * c.w as usize + w];
            let off = y * info.stride * bpp;
            let row = &mut self.fb[off..off + w * bpp];
            match (info.pixel_format, bpp) {
                (PixelFormat::Bgr, 4) => {
                    // 0x00RRGGBB in little endian is B, G, R, 0 — exactly BGRx.
                    let dst = unsafe { core::slice::from_raw_parts_mut(row.as_mut_ptr() as *mut u32, w) };
                    dst.copy_from_slice(src);
                }
                (PixelFormat::Rgb, 4) => {
                    let dst = unsafe { core::slice::from_raw_parts_mut(row.as_mut_ptr() as *mut u32, w) };
                    for (d, &p) in dst.iter_mut().zip(src) {
                        *d = ((p & 0xFF) << 16) | (p & 0xFF00) | ((p >> 16) & 0xFF);
                    }
                }
                (PixelFormat::Bgr, _) => {
                    for (i, &p) in src.iter().enumerate() {
                        row[i * bpp] = p as u8;
                        row[i * bpp + 1] = (p >> 8) as u8;
                        row[i * bpp + 2] = (p >> 16) as u8;
                    }
                }
                (PixelFormat::Rgb, _) => {
                    for (i, &p) in src.iter().enumerate() {
                        row[i * bpp] = (p >> 16) as u8;
                        row[i * bpp + 1] = (p >> 8) as u8;
                        row[i * bpp + 2] = p as u8;
                    }
                }
                _ => {
                    for (i, &p) in src.iter().enumerate() {
                        let g = (((p >> 16) & 0xFF) * 3 + ((p >> 8) & 0xFF) * 6 + (p & 0xFF)) / 10;
                        row[i * bpp] = g as u8;
                    }
                }
            }
        }
    }
}
