//! libstoa: the system-call interface for Stoa user programs (int 0x80; number in rax, args rdi/rsi).
#![no_std]

use core::arch::asm;
use core::fmt::{self, Write};

pub const SYS_WRITE: u64 = 0;
pub const SYS_EXIT: u64 = 1;
pub const SYS_YIELD: u64 = 2;
pub const SYS_TIME: u64 = 3;
pub const SYS_GETPID: u64 = 4;
pub const SYS_SLEEP: u64 = 5;

#[inline(always)]
unsafe fn syscall2(n: u64, a: u64, b: u64) -> u64 {
    let ret;
    asm!("int 0x80", inlateout("rax") n => ret, in("rdi") a, in("rsi") b, options(nostack));
    ret
}

pub fn write(s: &str) -> u64 {
    unsafe { syscall2(SYS_WRITE, s.as_ptr() as u64, s.len() as u64) }
}
pub fn exit(code: i64) -> ! {
    unsafe { syscall2(SYS_EXIT, code as u64, 0) };
    loop {}
}
pub fn yield_now() {
    unsafe { syscall2(SYS_YIELD, 0, 0) };
}
pub fn uptime_ms() -> u64 {
    unsafe { syscall2(SYS_TIME, 0, 0) }
}
pub fn getpid() -> u64 {
    unsafe { syscall2(SYS_GETPID, 0, 0) }
}
pub fn sleep_ms(ms: u64) {
    unsafe { syscall2(SYS_SLEEP, ms, 0) };
}

/// Formats into a fixed buffer (no heap in user programs) and writes it in one system call.
pub struct Out {
    buf: [u8; 512],
    len: usize,
}
impl Out {
    pub const fn new() -> Self {
        Self { buf: [0; 512], len: 0 }
    }
    pub fn flush(&mut self) {
        if self.len > 0 {
            write(unsafe { core::str::from_utf8_unchecked(&self.buf[..self.len]) });
            self.len = 0;
        }
    }
}
impl Write for Out {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        for &b in s.as_bytes() {
            if self.len == self.buf.len() {
                self.flush();
            }
            self.buf[self.len] = b;
            self.len += 1;
        }
        Ok(())
    }
}

#[macro_export]
macro_rules! println {
    ($($t:tt)*) => {{
        let mut o = $crate::Out::new();
        let _ = core::fmt::Write::write_fmt(&mut o, format_args!($($t)*));
        o.flush();
    }};
}

/// Program entry: `stoa::entry!(main);` where `fn main() -> i64`.
#[macro_export]
macro_rules! entry {
    ($main:path) => {
        #[no_mangle]
        pub extern "C" fn _start() -> ! {
            let code: i64 = $main();
            $crate::exit(code)
        }
        #[panic_handler]
        fn panic(info: &core::panic::PanicInfo) -> ! {
            $crate::println!("panic: {}", info);
            $crate::exit(101)
        }
    };
}
