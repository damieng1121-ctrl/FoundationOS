//! Preemptive multitasking: kernel threads and ring-3 user processes, scheduled round-robin on every
//! timer tick, plus the system-call interface (int 0x80) and the ELF loader for user programs.
//!
//! Context switches happen in the timer and system-call entry stubs: they push every general-purpose
//! register onto the current kernel stack, hand that stack pointer to `schedule`, and resume whichever
//! stack it returns (restoring that task's registers and returning with `iretq`, into ring 0 or ring 3).
use crate::{gdt, memory};
use alloc::collections::VecDeque;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;
use core::arch::naked_asm;
use core::sync::atomic::{AtomicU64, Ordering};
use spin::Mutex;
use x86_64::registers::control::{Cr3, Cr3Flags};
use x86_64::structures::paging::PhysFrame;
use x86_64::PhysAddr;

const KSTACK: usize = 32 * 1024;
const USER_STACK_TOP: u64 = 0x2000_0080_0000;
const USER_STACK_SIZE: u64 = 64 * 1024;
/// User programs live in this L4 slot (0x2000_0000_0000 .. 0x2080_0000_0000), private to each process.
const USER_L4_SLOT: usize = 64;
const USER_MIN: u64 = (USER_L4_SLOT as u64) << 39;
const USER_MAX: u64 = (USER_L4_SLOT as u64 + 1) << 39;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum State {
    Ready,
    Sleeping(u64),
    Dead(i64),
}

pub struct Task {
    pub id: u64,
    pub name: String,
    rsp: u64,
    _kstack: Vec<u8>,
    kstack_top: u64,
    user: Option<(u64, Vec<u64>)>, // (level-4 table, private frames)
    pub state: State,
    pub ticks: u64,
}

struct Sched {
    tasks: Vec<Task>,
    current: usize,
    next_id: u64,
    kernel_l4: u64,
}

static SCHED: Mutex<Option<Sched>> = Mutex::new(None);
pub static SWITCHES: AtomicU64 = AtomicU64::new(0);
/// Timer ticks that found the CPU idle (the desktop task halted, waiting for input).
pub static IDLE_TICKS: AtomicU64 = AtomicU64::new(0);
pub static IDLE: core::sync::atomic::AtomicBool = core::sync::atomic::AtomicBool::new(false);
/// Output from user programs: (pid, text), collected by the Terminal.
pub static CONSOLE: Mutex<VecDeque<(u64, String)>> = Mutex::new(VecDeque::new());

/// Saved registers on a kernel stack, in the order the entry stubs push them (lowest address first).
#[repr(C)]
struct Frame {
    r15: u64, r14: u64, r13: u64, r12: u64, r11: u64, r10: u64, r9: u64, r8: u64,
    rbp: u64, rdi: u64, rsi: u64, rdx: u64, rcx: u64, rbx: u64, rax: u64,
    rip: u64, cs: u64, rflags: u64, rsp: u64, ss: u64,
}

pub fn init() {
    let (l4, _) = Cr3::read();
    *SCHED.lock() = Some(Sched {
        tasks: vec![Task {
            id: 0,
            name: "desktop".into(),
            rsp: 0,
            _kstack: Vec::new(),
            kstack_top: 0,
            user: None,
            state: State::Ready,
            ticks: 0,
        }],
        current: 0,
        next_id: 1,
        kernel_l4: l4.start_address().as_u64(),
    });
    crate::klog!("kernel L4 slots in use: {:?}", memory::used_l4_slots());
    crate::klog!("scheduler: round-robin, preemptive at {} Hz", crate::interrupts::TIMER_HZ);
}

fn with<R>(f: impl FnOnce(&mut Sched) -> R) -> R {
    x86_64::instructions::interrupts::without_interrupts(|| f(SCHED.lock().as_mut().expect("scheduler not ready")))
}

/// Called from the timer and system-call stubs with interrupts off. Never allocates or frees memory.
fn schedule(rsp: u64, from_timer: bool) -> u64 {
    let Some(mut g) = SCHED.try_lock() else { return rsp };
    let Some(s) = g.as_mut() else { return rsp };
    let now = crate::sys::ticks();
    let cur = s.current;
    s.tasks[cur].rsp = rsp;
    if from_timer {
        if cur == 0 && IDLE.load(Ordering::Relaxed) {
            IDLE_TICKS.fetch_add(1, Ordering::Relaxed);
        } else {
            s.tasks[cur].ticks += 1;
        }
    }
    let n = s.tasks.len();
    let mut next = cur;
    for i in 1..=n {
        let j = (cur + i) % n;
        match s.tasks[j].state {
            State::Ready => {
                next = j;
                break;
            }
            State::Sleeping(until) if now >= until => {
                s.tasks[j].state = State::Ready;
                next = j;
                break;
            }
            _ => {}
        }
    }
    if next == cur && s.tasks[cur].state != State::Ready {
        next = 0; // nothing else runnable: the desktop task always is
    }
    if next != cur {
        SWITCHES.fetch_add(1, Ordering::Relaxed);
        s.current = next;
        let t = &s.tasks[next];
        let l4 = t.user.as_ref().map(|u| u.0).unwrap_or(s.kernel_l4);
        if t.user.is_some() {
            gdt::set_kernel_stack(t.kstack_top);
        }
        let (cur_l4, _) = Cr3::read();
        if cur_l4.start_address().as_u64() != l4 {
            unsafe { Cr3::write(PhysFrame::containing_address(PhysAddr::new(l4)), Cr3Flags::empty()) };
        }
    }
    s.tasks[next].rsp
}

fn new_stack_frame(entry: u64, arg: u64, user: Option<(u64, u64)>) -> (Vec<u8>, u64, u64) {
    let kstack = vec![0u8; KSTACK];
    let top = (kstack.as_ptr() as u64 + KSTACK as u64) & !0xF;
    let sel = gdt::selectors();
    let frame_addr = top - core::mem::size_of::<Frame>() as u64;
    let f = unsafe { &mut *(frame_addr as *mut Frame) };
    *f = Frame {
        r15: 0, r14: 0, r13: 0, r12: 0, r11: 0, r10: 0, r9: 0, r8: 0,
        rbp: 0, rdi: arg, rsi: 0, rdx: 0, rcx: 0, rbx: 0, rax: 0,
        rip: entry,
        cs: 0, rflags: 0x202, rsp: 0, ss: 0,
    };
    match user {
        Some((rip, rsp)) => {
            f.rip = rip;
            f.cs = (sel.user_code.0 | 3) as u64;
            f.ss = (sel.user_data.0 | 3) as u64;
            f.rsp = rsp;
        }
        None => {
            f.cs = sel.kernel_code.0 as u64;
            f.ss = sel.kernel_data.0 as u64;
            f.rsp = top - 8; // as if called: keeps the ABI's stack alignment
        }
    }
    (kstack, top, frame_addr)
}

extern "C" fn thread_start(entry: u64) -> ! {
    let f: fn() = unsafe { core::mem::transmute(entry as *const ()) };
    f();
    exit_current(0)
}

/// Start a kernel thread running `f`.
pub fn spawn(name: &str, f: fn()) -> u64 {
    let (kstack, top, rsp) = new_stack_frame(thread_start as usize as u64, f as usize as u64, None);
    with(|s| {
        let id = s.next_id;
        s.next_id += 1;
        s.tasks.push(Task { id, name: name.into(), rsp, _kstack: kstack, kstack_top: top, user: None,
            state: State::Ready, ticks: 0 });
        id
    })
}

/// Put the running kernel thread to sleep for about `ms` milliseconds.
pub fn sleep_ms(ms: u64) {
    let until = crate::sys::ticks() + (ms * crate::interrupts::TIMER_HZ).div_ceil(1000).max(1);
    with(|s| {
        let c = s.current;
        if c != 0 {
            s.tasks[c].state = State::Sleeping(until);
        }
    });
    // Give up the CPU now (system call from ring 0); the scheduler wakes us when the time is up.
    while crate::sys::ticks() < until {
        unsafe { core::arch::asm!("int 0x80", inlateout("rax") SYS_YIELD => _, out("rdi") _, out("rsi") _) };
    }
}

/// Mark the running task finished and give up the CPU for good.
pub fn exit_current(code: i64) -> ! {
    with(|s| {
        let c = s.current;
        s.tasks[c].state = State::Dead(code);
    });
    loop {
        x86_64::instructions::interrupts::enable_and_hlt();
    }
}

pub fn kill(id: u64) -> bool {
    if id == 0 {
        return false;
    }
    with(|s| match s.tasks.iter_mut().find(|t| t.id == id && !matches!(t.state, State::Dead(_))) {
        Some(t) => {
            t.state = State::Dead(-9);
            true
        }
        None => false,
    })
}

/// Free finished tasks (called from normal kernel context, never from an interrupt).
pub fn reap() {
    let dead: Vec<Task> = with(|s| {
        let cur = s.tasks[s.current].id;
        let mut out = Vec::new();
        let mut i = 1;
        while i < s.tasks.len() {
            if matches!(s.tasks[i].state, State::Dead(_)) && s.tasks[i].id != cur {
                out.push(s.tasks.remove(i));
                if s.current > i {
                    s.current -= 1;
                }
            } else {
                i += 1;
            }
        }
        out
    });
    for t in dead {
        if let State::Dead(code) = t.state {
            let msg = if code == -9 { "[killed]".to_string() } else { alloc::format!("[exited with code {}]", code) };
            CONSOLE.lock().push_back((t.id, msg));
            crate::klog!("task {} '{}' ended ({})", t.id, t.name, code);
        }
        if let Some((l4, frames)) = &t.user {
            memory::free_user(*l4, frames);
        }
    }
}

pub struct Info {
    pub id: u64,
    pub name: String,
    pub state: State,
    pub ticks: u64,
    pub user: bool,
}

pub fn tasks() -> Vec<Info> {
    with(|s| {
        s.tasks
            .iter()
            .map(|t| Info { id: t.id, name: t.name.clone(), state: t.state, ticks: t.ticks, user: t.user.is_some() })
            .collect()
    })
}

pub fn current_id() -> u64 {
    with(|s| s.tasks[s.current].id)
}

// ------------------------------------------------------------------ ELF loader + user processes

fn u16le(b: &[u8], o: usize) -> u16 {
    u16::from_le_bytes([b[o], b[o + 1]])
}
fn u32le(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes(b[o..o + 4].try_into().unwrap())
}
fn u64le(b: &[u8], o: usize) -> u64 {
    u64::from_le_bytes(b[o..o + 8].try_into().unwrap())
}

/// Load a static x86_64 ELF executable into a new address space and start it in ring 3.
pub fn spawn_elf(name: &str, elf: &[u8]) -> Result<u64, &'static str> {
    if elf.len() < 64 || &elf[0..4] != b"\x7fELF" || elf[4] != 2 || u16le(elf, 18) != 0x3E {
        return Err("not an x86_64 ELF file");
    }
    if u16le(elf, 16) != 2 {
        return Err("not a static executable");
    }
    if !memory::l4_slot_free(USER_L4_SLOT) {
        return Err("user address range is in use by the kernel");
    }
    let entry = u64le(elf, 24);
    let (phoff, phentsize, phnum) = (u64le(elf, 32) as usize, u16le(elf, 54) as usize, u16le(elf, 56) as usize);
    let l4 = memory::new_address_space().ok_or("out of memory")?;
    let mut frames = Vec::new();
    let fail = |l4: u64, frames: &Vec<u64>, e: &'static str| {
        memory::free_user(l4, frames);
        Err(e)
    };
    for i in 0..phnum {
        let o = phoff + i * phentsize;
        if o + 56 > elf.len() || u32le(elf, o) != 1 {
            continue; // not PT_LOAD
        }
        let (off, vaddr, filesz, memsz) =
            (u64le(elf, o + 8) as usize, u64le(elf, o + 16), u64le(elf, o + 32) as usize, u64le(elf, o + 40));
        if vaddr < USER_MIN || vaddr + memsz > USER_MAX || off + filesz > elf.len() {
            return fail(l4, &frames, "program loads outside the user area");
        }
        let start = vaddr & !0xFFF;
        match memory::map_user(l4, start, vaddr + memsz - start, true) {
            Ok(f) => frames.extend(f),
            Err(e) => return fail(l4, &frames, e),
        }
        if let Err(e) = memory::copy_to_user(l4, vaddr, &elf[off..off + filesz]) {
            return fail(l4, &frames, e);
        }
    }
    if entry < USER_MIN || entry >= USER_MAX {
        return fail(l4, &frames, "entry point outside the user area");
    }
    match memory::map_user(l4, USER_STACK_TOP - USER_STACK_SIZE, USER_STACK_SIZE, true) {
        Ok(f) => frames.extend(f),
        Err(e) => return fail(l4, &frames, e),
    }
    let (kstack, top, rsp) = new_stack_frame(0, 0, Some((entry, USER_STACK_TOP - 8)));
    Ok(with(|s| {
        let id = s.next_id;
        s.next_id += 1;
        s.tasks.push(Task { id, name: name.into(), rsp, _kstack: kstack, kstack_top: top, user: Some((l4, frames)),
            state: State::Ready, ticks: 0 });
        crate::klog!("process {} '{}' started (entry {:#x})", id, name, entry);
        id
    }))
}

/// Copy a user buffer into the kernel, checking every page is mapped in the caller's address space.
fn user_bytes(ptr: u64, len: u64) -> Option<Vec<u8>> {
    if len > 64 * 1024 || ptr < USER_MIN || ptr.checked_add(len)? > USER_MAX {
        return None;
    }
    use x86_64::structures::paging::{OffsetPageTable, PageTable, Translate};
    let (l4, _) = Cr3::read();
    let table = unsafe { &mut *(memory::phys_to_virt(l4.start_address().as_u64()) as *mut PageTable) };
    let mapper = unsafe {
        OffsetPageTable::new(table, x86_64::VirtAddr::new(memory::PHYS_OFFSET.load(Ordering::Relaxed)))
    };
    let mut out = Vec::with_capacity(len as usize);
    let mut done = 0;
    while done < len {
        let va = ptr + done;
        let pa = mapper.translate_addr(x86_64::VirtAddr::new(va))?.as_u64();
        let n = (4096 - (va & 0xFFF)).min(len - done);
        out.extend_from_slice(unsafe { core::slice::from_raw_parts(memory::phys_to_virt(pa) as *const u8, n as usize) });
        done += n;
    }
    Some(out)
}

// System call numbers (shared with research/user/src/lib.rs).
const SYS_WRITE: u64 = 0;
const SYS_EXIT: u64 = 1;
const SYS_YIELD: u64 = 2;
const SYS_TIME: u64 = 3;
const SYS_GETPID: u64 = 4;
const SYS_SLEEP: u64 = 5;

extern "C" fn syscall_inner(rsp: u64) -> u64 {
    let f = unsafe { &mut *(rsp as *mut Frame) };
    match f.rax {
        SYS_WRITE => {
            // Allocating needs interrupts on (the heap lock may be held by a preempted task).
            x86_64::instructions::interrupts::enable();
            f.rax = match user_bytes(f.rdi, f.rsi) {
                Some(b) => {
                    let pid = current_id();
                    CONSOLE.lock().push_back((pid, String::from_utf8_lossy(&b).into_owned()));
                    b.len() as u64
                }
                None => u64::MAX,
            };
            x86_64::instructions::interrupts::disable();
            rsp
        }
        SYS_EXIT => {
            if let Some(mut g) = SCHED.try_lock() {
                if let Some(s) = g.as_mut() {
                    let c = s.current;
                    s.tasks[c].state = State::Dead(f.rdi as i64);
                }
            }
            schedule(rsp, false)
        }
        SYS_YIELD => schedule(rsp, false),
        SYS_TIME => {
            f.rax = crate::sys::uptime_ms();
            rsp
        }
        SYS_GETPID => {
            f.rax = SCHED.try_lock().and_then(|g| g.as_ref().map(|s| s.tasks[s.current].id)).unwrap_or(0);
            rsp
        }
        SYS_SLEEP => {
            let until = crate::sys::ticks() + (f.rdi * crate::interrupts::TIMER_HZ).div_ceil(1000);
            if let Some(mut g) = SCHED.try_lock() {
                if let Some(s) = g.as_mut() {
                    let c = s.current;
                    s.tasks[c].state = State::Sleeping(until);
                }
            }
            f.rax = 0;
            schedule(rsp, false)
        }
        _ => {
            f.rax = u64::MAX;
            rsp
        }
    }
}

extern "C" fn timer_inner(rsp: u64) -> u64 {
    crate::interrupts::timer_tick();
    schedule(rsp, true)
}

macro_rules! entry_stub {
    ($name:ident, $inner:ident) => {
        #[unsafe(naked)]
        pub extern "C" fn $name() {
            naked_asm!(
                "push rax", "push rbx", "push rcx", "push rdx", "push rsi", "push rdi", "push rbp",
                "push r8", "push r9", "push r10", "push r11", "push r12", "push r13", "push r14", "push r15",
                "mov rdi, rsp",
                "call {inner}",
                "mov rsp, rax",
                "pop r15", "pop r14", "pop r13", "pop r12", "pop r11", "pop r10", "pop r9", "pop r8",
                "pop rbp", "pop rdi", "pop rsi", "pop rdx", "pop rcx", "pop rbx", "pop rax",
                "iretq",
                inner = sym $inner,
            )
        }
    };
}

entry_stub!(timer_entry, timer_inner);
entry_stub!(syscall_entry, syscall_inner);

/// A user program faulted: end it instead of the whole system.
pub fn kill_faulting_user(what: &str) -> ! {
    x86_64::instructions::interrupts::enable(); // the heap lock may be held by a preempted task
    let id = current_id();
    crate::klog!("process {} crashed: {}", id, what);
    CONSOLE.lock().push_back((id, alloc::format!("[crashed: {}]", what)));
    exit_current(-11)
}
