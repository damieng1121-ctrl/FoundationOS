//! Minimal 16550 UART driver on COM1, used for kernel debug logging.
use core::fmt::{self, Write};
use spin::Mutex;
use x86_64::instructions::port::Port;

const COM1: u16 = 0x3F8;

unsafe fn outb(port: u16, v: u8) {
    Port::<u8>::new(port).write(v)
}
unsafe fn inb(port: u16) -> u8 {
    Port::<u8>::new(port).read()
}

pub fn init() {
    unsafe {
        outb(COM1 + 1, 0x00); // disable interrupts
        outb(COM1 + 3, 0x80); // enable DLAB
        outb(COM1, 0x03); // 38400 baud
        outb(COM1 + 1, 0x00);
        outb(COM1 + 3, 0x03); // 8N1
        outb(COM1 + 2, 0xC7); // FIFO
        outb(COM1 + 4, 0x0B);
    }
}

fn putc(b: u8) {
    unsafe {
        let mut spins = 0u32;
        while inb(COM1 + 5) & 0x20 == 0 && spins < 100_000 {
            spins += 1;
        }
        outb(COM1, b);
    }
}

struct Serial;
impl Write for Serial {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        for b in s.bytes() {
            if b == b'\n' {
                putc(b'\r');
            }
            putc(b);
        }
        Ok(())
    }
}

static LOCK: Mutex<()> = Mutex::new(());

pub fn _print(args: fmt::Arguments) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        let _g = LOCK.lock();
        let _ = Serial.write_fmt(args);
    });
}

/// Log to the serial port and (once the heap is up) to the in-memory kernel log.
#[macro_export]
macro_rules! klog {
    ($($arg:tt)*) => {{
        $crate::serial::_print(format_args!("[foundation] {}\n", format_args!($($arg)*)));
        $crate::sys::push_log(format_args!($($arg)*));
    }};
}
