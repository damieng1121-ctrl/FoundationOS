//! PS/2 mouse: controller setup and 3-byte packet decoding.
use x86_64::instructions::port::Port;

unsafe fn outb(p: u16, v: u8) {
    Port::<u8>::new(p).write(v)
}
unsafe fn inb(p: u16) -> u8 {
    Port::<u8>::new(p).read()
}
fn wait_write() {
    for _ in 0..100_000 {
        if unsafe { inb(0x64) } & 2 == 0 {
            return;
        }
    }
}
fn wait_read() -> bool {
    for _ in 0..100_000 {
        if unsafe { inb(0x64) } & 1 == 1 {
            return true;
        }
    }
    false
}
fn cmd(c: u8) {
    wait_write();
    unsafe { outb(0x64, c) }
}
fn data(d: u8) {
    wait_write();
    unsafe { outb(0x60, d) }
}
fn read() -> u8 {
    wait_read();
    unsafe { inb(0x60) }
}
fn mouse_write(b: u8) {
    cmd(0xD4);
    data(b);
    let _ack = read();
}

/// Must run with interrupts disabled.
pub fn init() {
    // Flush anything pending in the output buffer.
    while unsafe { inb(0x64) } & 1 == 1 {
        unsafe { inb(0x60) };
    }
    cmd(0xA8); // enable auxiliary device
    cmd(0x20); // read controller config
    let mut status = read();
    status |= 0b11; // IRQ1 + IRQ12 enabled
    status &= !0x20; // enable mouse clock
    cmd(0x60);
    data(status);
    mouse_write(0xF6); // defaults
    mouse_write(0xF4); // enable data reporting
}

#[derive(Clone, Copy, Debug)]
#[allow(dead_code)]
pub struct MouseEvent {
    pub dx: i32,
    pub dy: i32,
    pub left: bool,
    pub right: bool,
}

pub struct MouseDecoder {
    bytes: [u8; 3],
    idx: usize,
}

impl MouseDecoder {
    pub const fn new() -> Self {
        Self { bytes: [0; 3], idx: 0 }
    }
    pub fn feed(&mut self, b: u8) -> Option<MouseEvent> {
        if self.idx == 0 && b & 0x08 == 0 {
            return None; // out of sync; wait for a valid first byte
        }
        self.bytes[self.idx] = b;
        self.idx += 1;
        if self.idx < 3 {
            return None;
        }
        self.idx = 0;
        let f = self.bytes[0];
        if f & 0xC0 != 0 {
            return None; // overflow
        }
        let mut dx = self.bytes[1] as i32;
        let mut dy = self.bytes[2] as i32;
        if f & 0x10 != 0 {
            dx -= 256;
        }
        if f & 0x20 != 0 {
            dy -= 256;
        }
        Some(MouseEvent { dx, dy: -dy, left: f & 1 != 0, right: f & 2 != 0 })
    }
}
