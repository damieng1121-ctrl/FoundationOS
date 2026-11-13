//! IDT, legacy PIC, PIT timer and the IRQ handlers for timer, keyboard and mouse.
use crate::gdt;
use core::sync::atomic::{AtomicU64, AtomicU8, AtomicUsize, Ordering};
use pic8259::ChainedPics;
use spin::{Mutex, Once};
use x86_64::instructions::port::Port;
use x86_64::structures::idt::{InterruptDescriptorTable, InterruptStackFrame, PageFaultErrorCode};

pub const PIC_1_OFFSET: u8 = 32;
pub const PIC_2_OFFSET: u8 = 40;
pub const TIMER_HZ: u64 = 100;

const IRQ_TIMER: u8 = PIC_1_OFFSET;
const IRQ_KEYBOARD: u8 = PIC_1_OFFSET + 1;
const IRQ_MOUSE: u8 = PIC_2_OFFSET + 4;

pub static PICS: Mutex<ChainedPics> = Mutex::new(unsafe { ChainedPics::new(PIC_1_OFFSET, PIC_2_OFFSET) });
pub static TICKS: AtomicU64 = AtomicU64::new(0);

/// Lock-free single-producer/single-consumer byte queue (IRQ handler -> main loop).
pub struct RingBuffer {
    buf: [AtomicU8; 512],
    head: AtomicUsize,
    tail: AtomicUsize,
}

impl RingBuffer {
    pub const fn new() -> Self {
        Self { buf: [const { AtomicU8::new(0) }; 512], head: AtomicUsize::new(0), tail: AtomicUsize::new(0) }
    }
    pub fn push(&self, b: u8) {
        let h = self.head.load(Ordering::Acquire);
        let next = (h + 1) % 512;
        if next == self.tail.load(Ordering::Acquire) {
            return; // full: drop
        }
        self.buf[h].store(b, Ordering::Relaxed);
        self.head.store(next, Ordering::Release);
    }
    pub fn pop(&self) -> Option<u8> {
        let t = self.tail.load(Ordering::Acquire);
        if t == self.head.load(Ordering::Acquire) {
            return None;
        }
        let b = self.buf[t].load(Ordering::Relaxed);
        self.tail.store((t + 1) % 512, Ordering::Release);
        Some(b)
    }
    pub fn is_empty(&self) -> bool {
        self.head.load(Ordering::Acquire) == self.tail.load(Ordering::Acquire)
    }
}

pub static KEY_QUEUE: RingBuffer = RingBuffer::new();
pub static MOUSE_QUEUE: RingBuffer = RingBuffer::new();

static IDT: Once<InterruptDescriptorTable> = Once::new();

pub fn init_idt() {
    let idt = IDT.call_once(|| {
        let mut idt = InterruptDescriptorTable::new();
        idt.breakpoint.set_handler_fn(breakpoint);
        idt.page_fault.set_handler_fn(page_fault);
        idt.general_protection_fault.set_handler_fn(gpf);
        idt.invalid_opcode.set_handler_fn(invalid_opcode);
        unsafe {
            idt.double_fault.set_handler_fn(double_fault).set_stack_index(gdt::DOUBLE_FAULT_IST_INDEX);
        }
        idt[IRQ_TIMER].set_handler_fn(timer);
        idt[IRQ_KEYBOARD].set_handler_fn(keyboard);
        idt[IRQ_MOUSE].set_handler_fn(mouse);
        idt
    });
    idt.load();
}

pub fn init_pics_and_pit() {
    unsafe {
        let mut pics = PICS.lock();
        pics.initialize();
        // Unmask IRQ0 (timer), IRQ1 (keyboard), IRQ2 (cascade) and IRQ12 (mouse).
        pics.write_masks(0b1111_1000, 0b1110_1111);
        // Program PIT channel 0 to TIMER_HZ.
        let divisor = (1_193_182 / TIMER_HZ) as u16;
        Port::<u8>::new(0x43).write(0x36);
        Port::<u8>::new(0x40).write((divisor & 0xFF) as u8);
        Port::<u8>::new(0x40).write((divisor >> 8) as u8);
    }
}

extern "x86-interrupt" fn breakpoint(frame: InterruptStackFrame) {
    crate::klog!("BREAKPOINT\n{:#?}", frame);
}

extern "x86-interrupt" fn invalid_opcode(frame: InterruptStackFrame) {
    panic!("INVALID OPCODE\n{:#?}", frame);
}

extern "x86-interrupt" fn gpf(frame: InterruptStackFrame, code: u64) {
    panic!("GENERAL PROTECTION FAULT (code {:#x})\n{:#?}", code, frame);
}

extern "x86-interrupt" fn double_fault(frame: InterruptStackFrame, _code: u64) -> ! {
    panic!("DOUBLE FAULT\n{:#?}", frame);
}

extern "x86-interrupt" fn page_fault(frame: InterruptStackFrame, code: PageFaultErrorCode) {
    use x86_64::registers::control::Cr2;
    panic!("PAGE FAULT at {:?} ({:?})\n{:#?}", Cr2::read(), code, frame);
}

extern "x86-interrupt" fn timer(_frame: InterruptStackFrame) {
    TICKS.fetch_add(1, Ordering::Relaxed);
    unsafe { PICS.lock().notify_end_of_interrupt(IRQ_TIMER) };
}

extern "x86-interrupt" fn keyboard(_frame: InterruptStackFrame) {
    let b: u8 = unsafe { Port::new(0x60).read() };
    KEY_QUEUE.push(b);
    unsafe { PICS.lock().notify_end_of_interrupt(IRQ_KEYBOARD) };
}

extern "x86-interrupt" fn mouse(_frame: InterruptStackFrame) {
    let b: u8 = unsafe { Port::new(0x60).read() };
    MOUSE_QUEUE.push(b);
    unsafe { PICS.lock().notify_end_of_interrupt(IRQ_MOUSE) };
}
