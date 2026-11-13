//! Paging setup and a physical frame allocator backed by the bootloader's memory map.
use bootloader_api::info::{MemoryRegion, MemoryRegionKind};
use x86_64::registers::control::Cr3;
use x86_64::structures::paging::{FrameAllocator, OffsetPageTable, PageTable, PhysFrame, Size4KiB};
use x86_64::{PhysAddr, VirtAddr};

pub unsafe fn init(physical_memory_offset: VirtAddr) -> OffsetPageTable<'static> {
    let (frame, _) = Cr3::read();
    let virt = physical_memory_offset + frame.start_address().as_u64();
    let l4: &'static mut PageTable = &mut *virt.as_mut_ptr();
    OffsetPageTable::new(l4, physical_memory_offset)
}

pub struct BootInfoFrameAllocator {
    regions: &'static [MemoryRegion],
    region: usize,
    next: u64,
    pub allocated: u64,
}

impl BootInfoFrameAllocator {
    pub fn new(regions: &'static [MemoryRegion]) -> Self {
        Self { regions, region: 0, next: 0, allocated: 0 }
    }

    pub fn usable_bytes(&self) -> u64 {
        self.regions.iter().filter(|r| r.kind == MemoryRegionKind::Usable).map(|r| r.end - r.start).sum()
    }
}

unsafe impl FrameAllocator<Size4KiB> for BootInfoFrameAllocator {
    fn allocate_frame(&mut self) -> Option<PhysFrame> {
        while self.region < self.regions.len() {
            let r = &self.regions[self.region];
            if r.kind == MemoryRegionKind::Usable {
                let start = (r.start + 0xFFF) & !0xFFF;
                if self.next < start {
                    self.next = start;
                }
                if self.next + 4096 <= r.end {
                    let f = PhysFrame::containing_address(PhysAddr::new(self.next));
                    self.next += 4096;
                    self.allocated += 1;
                    return Some(f);
                }
            }
            self.region += 1;
        }
        None
    }
}
