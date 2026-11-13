//! Kernel heap: maps a fixed virtual range and hands it to a linked-list allocator.
use linked_list_allocator::LockedHeap;
use x86_64::structures::paging::mapper::MapToError;
use x86_64::structures::paging::{FrameAllocator, Mapper, Page, PageTableFlags, Size4KiB};
use x86_64::VirtAddr;

pub const HEAP_START: u64 = 0x_4444_4444_0000;
pub const HEAP_SIZE: usize = 48 * 1024 * 1024;

#[global_allocator]
pub static ALLOCATOR: LockedHeap = LockedHeap::empty();

pub fn init_heap(
    mapper: &mut impl Mapper<Size4KiB>,
    frames: &mut impl FrameAllocator<Size4KiB>,
) -> Result<(), MapToError<Size4KiB>> {
    let start = Page::containing_address(VirtAddr::new(HEAP_START));
    let end = Page::containing_address(VirtAddr::new(HEAP_START + HEAP_SIZE as u64 - 1));
    for page in Page::range_inclusive(start, end) {
        let frame = frames.allocate_frame().ok_or(MapToError::FrameAllocationFailed)?;
        let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
        unsafe { mapper.map_to(page, frame, flags, frames)?.flush() };
    }
    unsafe { ALLOCATOR.lock().init(HEAP_START as *mut u8, HEAP_SIZE) };
    Ok(())
}

pub fn stats() -> (usize, usize) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        let h = ALLOCATOR.lock();
        (h.used(), h.size())
    })
}
