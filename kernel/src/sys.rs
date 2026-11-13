//! Shared system state: uptime, memory stats, kernel log, CPU info and app launch requests.
use crate::apps::AppKind;
use crate::interrupts::{TICKS, TIMER_HZ};
use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use spin::{Mutex, Once};
use x86_64::instructions::port::Port;

pub static HEAP_READY: AtomicBool = AtomicBool::new(false);
pub static PHYS_USABLE: AtomicU64 = AtomicU64::new(0);
pub static FRAMES_USED: AtomicU64 = AtomicU64::new(0);
pub static SCREEN_W: AtomicU32 = AtomicU32::new(0);
pub static SCREEN_H: AtomicU32 = AtomicU32::new(0);
pub static FRAMES_DRAWN: AtomicU64 = AtomicU64::new(0);

static LOG: Mutex<Vec<String>> = Mutex::new(Vec::new());
pub static WINDOWS: Mutex<Vec<String>> = Mutex::new(Vec::new());
static REQUESTS: Mutex<Vec<Request>> = Mutex::new(Vec::new());
static CPU_BRAND: Once<String> = Once::new();

pub enum Request {
    Open(AppKind),
    Edit(String),
}

pub fn request(r: Request) {
    REQUESTS.lock().push(r);
}
pub fn take_requests() -> Vec<Request> {
    core::mem::take(&mut *REQUESTS.lock())
}

pub fn push_log(args: core::fmt::Arguments) {
    if HEAP_READY.load(Ordering::Acquire) {
        if let Some(mut l) = LOG.try_lock() {
            l.push(format!("[{:>7}] {}", format_secs(uptime_ms()), args));
        }
    }
}
pub fn log_lines() -> Vec<String> {
    LOG.lock().clone()
}

pub fn ticks() -> u64 {
    TICKS.load(Ordering::Relaxed)
}
pub fn uptime_ms() -> u64 {
    ticks() * 1000 / TIMER_HZ
}
fn format_secs(ms: u64) -> String {
    format!("{}.{:02}", ms / 1000, (ms % 1000) / 10)
}
pub fn uptime_string() -> String {
    let s = uptime_ms() / 1000;
    format!("{:02}:{:02}:{:02}", s / 3600, (s / 60) % 60, s % 60)
}

pub fn human_bytes(b: u64) -> String {
    if b >= 1 << 30 {
        format!("{}.{} GiB", b >> 30, ((b % (1 << 30)) * 10) >> 30)
    } else if b >= 1 << 20 {
        format!("{}.{} MiB", b >> 20, ((b % (1 << 20)) * 10) >> 20)
    } else if b >= 1 << 10 {
        format!("{} KiB", b >> 10)
    } else {
        format!("{} B", b)
    }
}

#[allow(unused_unsafe)]
pub fn cpu_brand() -> &'static str {
    CPU_BRAND.call_once(|| {
        use core::arch::x86_64::__cpuid;
        let max = unsafe { __cpuid(0x8000_0000) }.eax;
        if max < 0x8000_0004 {
            let r = unsafe { __cpuid(0) };
            let mut v = Vec::new();
            for reg in [r.ebx, r.edx, r.ecx] {
                v.extend_from_slice(&reg.to_le_bytes());
            }
            return String::from_utf8_lossy(&v).into_owned();
        }
        let mut bytes = Vec::new();
        for leaf in 0x8000_0002u32..=0x8000_0004 {
            let r = unsafe { __cpuid(leaf) };
            for reg in [r.eax, r.ebx, r.ecx, r.edx] {
                bytes.extend_from_slice(&reg.to_le_bytes());
            }
        }
        let s = String::from_utf8_lossy(&bytes).into_owned();
        String::from(s.trim_matches(|c: char| c == '\0' || c == ' '))
    })
}

pub fn reboot() -> ! {
    unsafe {
        x86_64::instructions::interrupts::disable();
        Port::<u8>::new(0x64).write(0xFE);
    }
    loop {
        x86_64::instructions::hlt();
    }
}

pub fn shutdown() -> ! {
    unsafe {
        // QEMU (newer i440fx/q35 ACPI), Bochs/old QEMU, VirtualBox.
        Port::<u16>::new(0x604).write(0x2000);
        Port::<u16>::new(0xB004).write(0x2000);
        Port::<u16>::new(0x4004).write(0x3400);
    }
    loop {
        x86_64::instructions::hlt();
    }
}
