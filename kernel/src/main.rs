//! Foundation OS kernel entry point.
#![no_std]
#![no_main]
#![feature(abi_x86_interrupt)]

extern crate alloc;

mod allocator;
mod apps;
mod fs;
mod gdt;
mod gfx;
mod interrupts;
mod mathx;
mod memory;
mod mouse;
mod rtc;
mod serial;
mod sys;
mod wm;

use apps::{AppKind, Key};
use bootloader_api::config::Mapping;
use bootloader_api::info::MemoryRegion;
use bootloader_api::{entry_point, BootInfo, BootloaderConfig};
use core::panic::PanicInfo;
use core::sync::atomic::Ordering;
use pc_keyboard::{layouts, DecodedKey, HandleControl, KeyCode, Keyboard, ScancodeSet1};
use x86_64::VirtAddr;

pub static BOOTLOADER_CONFIG: BootloaderConfig = {
    let mut c = BootloaderConfig::new_default();
    c.mappings.physical_memory = Some(Mapping::Dynamic);
    c.kernel_stack_size = 512 * 1024;
    c
};

entry_point!(kernel_main, config = &BOOTLOADER_CONFIG);

fn kernel_main(boot_info: &'static mut BootInfo) -> ! {
    serial::init();
    klog!("Foundation OS 0.1 booting");

    gdt::init();
    interrupts::init_idt();
    klog!("GDT, TSS and IDT loaded");

    let phys_offset = VirtAddr::new(boot_info.physical_memory_offset.into_option().expect("no physical memory mapping"));
    let mut mapper = unsafe { memory::init(phys_offset) };
    let regions: &'static [MemoryRegion] =
        unsafe { core::slice::from_raw_parts(boot_info.memory_regions.as_ptr(), boot_info.memory_regions.len()) };
    let mut frames = memory::BootInfoFrameAllocator::new(regions);
    allocator::init_heap(&mut mapper, &mut frames).expect("heap initialisation failed");
    sys::HEAP_READY.store(true, Ordering::Release);
    sys::PHYS_USABLE.store(frames.usable_bytes(), Ordering::Relaxed);
    sys::FRAMES_USED.store(frames.allocated, Ordering::Relaxed);
    klog!("paging ready, heap {} at {:#x}", sys::human_bytes(allocator::HEAP_SIZE as u64), allocator::HEAP_START);
    klog!("physical memory: {} usable", sys::human_bytes(frames.usable_bytes()));

    let fb = boot_info.framebuffer.take().expect("no framebuffer");
    let info = fb.info();
    let mut screen = gfx::Screen::new(fb.into_buffer(), info);
    sys::SCREEN_W.store(info.width as u32, Ordering::Relaxed);
    sys::SCREEN_H.store(info.height as u32, Ordering::Relaxed);
    klog!("framebuffer {}x{} {:?} {}bpp", info.width, info.height, info.pixel_format, info.bytes_per_pixel * 8);

    fs::init();
    mouse::init();
    interrupts::init_pics_and_pit();
    x86_64::instructions::interrupts::enable();
    klog!("interrupts enabled; PIT at {} Hz; cpu: {}", interrupts::TIMER_HZ, sys::cpu_brand());

    let mut canvas = gfx::Canvas::new(info.width as i32, info.height as i32);
    let mut desktop = wm::Desktop::new(info.width as i32, info.height as i32);
    desktop.open(AppKind::About);
    desktop.open(AppKind::Terminal);
    klog!("desktop ready");

    let mut kb = Keyboard::new(ScancodeSet1::new(), layouts::Us104Key, HandleControl::Ignore);
    let mut md = mouse::MouseDecoder::new();

    loop {
        while let Some(sc) = interrupts::KEY_QUEUE.pop() {
            if let Ok(Some(ev)) = kb.add_byte(sc) {
                if let Some(k) = kb.process_keyevent(ev) {
                    let key = match k {
                        DecodedKey::Unicode('\n') | DecodedKey::Unicode('\r') => Some(Key::Enter),
                        DecodedKey::Unicode('\u{8}') => Some(Key::Backspace),
                        DecodedKey::Unicode('\t') => Some(Key::Tab),
                        DecodedKey::Unicode('\u{1b}') => Some(Key::Esc),
                        DecodedKey::Unicode(c) if !c.is_control() => Some(Key::Char(c)),
                        DecodedKey::RawKey(KeyCode::ArrowUp) => Some(Key::Up),
                        DecodedKey::RawKey(KeyCode::ArrowDown) => Some(Key::Down),
                        DecodedKey::RawKey(KeyCode::ArrowLeft) => Some(Key::Left),
                        DecodedKey::RawKey(KeyCode::ArrowRight) => Some(Key::Right),
                        _ => None,
                    };
                    if let Some(key) = key {
                        desktop.key(key);
                    }
                }
            }
        }
        while let Some(b) = interrupts::MOUSE_QUEUE.pop() {
            if let Some(ev) = md.feed(b) {
                desktop.mouse(ev);
            }
        }
        desktop.tick();
        if desktop.dirty {
            desktop.draw(&mut canvas);
            screen.present(&canvas);
            sys::FRAMES_DRAWN.fetch_add(1, Ordering::Relaxed);
        }
        // Sleep until the next interrupt unless input arrived meanwhile.
        x86_64::instructions::interrupts::disable();
        if interrupts::KEY_QUEUE.is_empty() && interrupts::MOUSE_QUEUE.is_empty() {
            x86_64::instructions::interrupts::enable_and_hlt();
        } else {
            x86_64::instructions::interrupts::enable();
        }
    }
}

#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    x86_64::instructions::interrupts::disable();
    serial::_print(format_args!("\n*** KERNEL PANIC ***\n{}\n", info));
    loop {
        x86_64::instructions::hlt();
    }
}
