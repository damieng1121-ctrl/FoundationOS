//! Paging and physical memory: the kernel's page tables, a frame allocator backed by the bootloader's
//! memory map (with a free list for reuse), MMIO mapping for device registers and per-process address
//! spaces for user programs.
use bootloader_api::info::{MemoryRegion, MemoryRegionKind};
use alloc::vec::Vec;
use core::sync::atomic::{AtomicU64, Ordering};
use spin::Mutex;
use x86_64::registers::control::Cr3;
use x86_64::structures::paging::{
    FrameAllocator, FrameDeallocator, Mapper, OffsetPageTable, Page, PageTable, PageTableFlags as F, PhysFrame,
    Size4KiB, Translate,
};
use x86_64::{PhysAddr, VirtAddr};

pub static PHYS_OFFSET: AtomicU64 = AtomicU64::new(0);
const MMIO_BASE: u64 = 0x5555_0000_0000;
static MMIO_NEXT: AtomicU64 = AtomicU64::new(MMIO_BASE);

pub unsafe fn init(physical_memory_offset: VirtAddr) -> OffsetPageTable<'static> {
    PHYS_OFFSET.store(physical_memory_offset.as_u64(), Ordering::Relaxed);
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
    free: Vec<PhysFrame>,
}

impl BootInfoFrameAllocator {
    pub fn new(regions: &'static [MemoryRegion]) -> Self {
        Self { regions, region: 0, next: 0, allocated: 0, free: Vec::new() }
    }

    pub fn usable_bytes(&self) -> u64 {
        self.regions.iter().filter(|r| r.kind == MemoryRegionKind::Usable).map(|r| r.end - r.start).sum()
    }
}

unsafe impl FrameAllocator<Size4KiB> for BootInfoFrameAllocator {
    fn allocate_frame(&mut self) -> Option<PhysFrame> {
        if let Some(f) = self.free.pop() {
            self.allocated += 1;
            return Some(f);
        }
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

impl FrameDeallocator<Size4KiB> for BootInfoFrameAllocator {
    unsafe fn deallocate_frame(&mut self, frame: PhysFrame) {
        self.allocated -= 1;
        self.free.push(frame);
    }
}

pub struct Memory {
    pub mapper: OffsetPageTable<'static>,
    pub frames: BootInfoFrameAllocator,
}

pub static MEM: Mutex<Option<Memory>> = Mutex::new(None);

pub fn install(mapper: OffsetPageTable<'static>, frames: BootInfoFrameAllocator) {
    *MEM.lock() = Some(Memory { mapper, frames });
}

fn with<R>(f: impl FnOnce(&mut Memory) -> R) -> R {
    x86_64::instructions::interrupts::without_interrupts(|| f(MEM.lock().as_mut().expect("memory not ready")))
}

pub fn phys_to_virt(p: u64) -> u64 {
    PHYS_OFFSET.load(Ordering::Relaxed) + p
}

pub fn frames_used() -> u64 {
    with(|m| m.frames.allocated)
}

/// A zeroed physical frame (for DMA buffers, page tables...). Returns its physical address.
pub fn alloc_frame() -> Option<u64> {
    let f = with(|m| m.frames.allocate_frame())?;
    let p = f.start_address().as_u64();
    unsafe { core::ptr::write_bytes(phys_to_virt(p) as *mut u8, 0, 4096) };
    Some(p)
}

/// `n` physically contiguous zeroed frames (best effort: works while the boot allocator is linear).
pub fn alloc_contiguous(n: usize) -> Option<u64> {
    with(|m| {
        let first = m.frames.allocate_frame()?;
        let mut last = first;
        for _ in 1..n {
            let f = m.frames.allocate_frame()?;
            if f.start_address().as_u64() != last.start_address().as_u64() + 4096 {
                return None;
            }
            last = f;
        }
        Some(first.start_address().as_u64())
    })
    .inspect(|&p| unsafe { core::ptr::write_bytes(phys_to_virt(p) as *mut u8, 0, n * 4096) })
}

/// Map device registers (uncached) and return their virtual address.
pub fn map_mmio(phys: u64, size: u64) -> u64 {
    let pages = size.div_ceil(4096);
    let virt = MMIO_NEXT.fetch_add(pages * 4096 + 4096, Ordering::Relaxed);
    with(|m| {
        for i in 0..pages {
            let page = Page::<Size4KiB>::containing_address(VirtAddr::new(virt + i * 4096));
            let frame = PhysFrame::containing_address(PhysAddr::new((phys & !0xFFF) + i * 4096));
            let flags = F::PRESENT | F::WRITABLE | F::NO_CACHE | F::WRITE_THROUGH | F::NO_EXECUTE;
            unsafe { m.mapper.map_to(page, frame, flags, &mut m.frames).expect("mmio map").flush() };
        }
    });
    virt + (phys & 0xFFF)
}

pub fn used_l4_slots() -> Vec<usize> {
    with(|m| (0..512).filter(|&i| !m.mapper.level_4_table()[i].is_unused()).collect())
}

/// Is this L4 slot unused by the kernel (so user programs can live there)?
pub fn l4_slot_free(index: usize) -> bool {
    with(|m| m.mapper.level_4_table()[index].is_unused())
}

/// A new address space: a fresh level-4 table sharing every kernel mapping. Returns its physical address.
pub fn new_address_space() -> Option<u64> {
    let l4 = alloc_frame()?;
    with(|m| {
        let src = m.mapper.level_4_table();
        let dst = unsafe { &mut *(phys_to_virt(l4) as *mut PageTable) };
        for i in 0..512 {
            dst[i] = src[i].clone();
        }
    });
    Some(l4)
}

/// Map `len` bytes at `virt` (page aligned) into address space `l4` as user pages; returns the frames.
pub fn map_user(l4: u64, virt: u64, len: u64, writable: bool) -> Result<Vec<u64>, &'static str> {
    let off = VirtAddr::new(PHYS_OFFSET.load(Ordering::Relaxed));
    with(|m| {
        let table = unsafe { &mut *(phys_to_virt(l4) as *mut PageTable) };
        let mut mapper = unsafe { OffsetPageTable::new(table, off) };
        let mut frames = Vec::new();
        for i in 0..len.div_ceil(4096) {
            let page = Page::<Size4KiB>::containing_address(VirtAddr::new(virt + i * 4096));
            if mapper.translate_addr(page.start_address()).is_some() {
                continue; // already mapped (segments sharing a page)
            }
            let frame = m.frames.allocate_frame().ok_or("out of memory")?;
            unsafe { core::ptr::write_bytes(phys_to_virt(frame.start_address().as_u64()) as *mut u8, 0, 4096) };
            let mut flags = F::PRESENT | F::USER_ACCESSIBLE;
            if writable {
                flags |= F::WRITABLE;
            }
            unsafe {
                mapper.map_to_with_table_flags(page, frame, flags, F::PRESENT | F::WRITABLE | F::USER_ACCESSIBLE,
                    &mut m.frames).map_err(|_| "map failed")?.ignore()
            };
            frames.push(frame.start_address().as_u64());
        }
        Ok(frames)
    })
}

/// Copy bytes into an address space at a user virtual address (via the physical memory window).
pub fn copy_to_user(l4: u64, virt: u64, data: &[u8]) -> Result<(), &'static str> {
    let off = VirtAddr::new(PHYS_OFFSET.load(Ordering::Relaxed));
    let table = unsafe { &mut *(phys_to_virt(l4) as *mut PageTable) };
    let mapper = unsafe { OffsetPageTable::new(table, off) };
    let mut done = 0;
    while done < data.len() {
        let va = virt + done as u64;
        let pa = mapper.translate_addr(VirtAddr::new(va)).ok_or("not mapped")?.as_u64();
        let n = (4096 - (va & 0xFFF) as usize).min(data.len() - done);
        unsafe { core::ptr::copy_nonoverlapping(data[done..].as_ptr(), phys_to_virt(pa) as *mut u8, n) };
        done += n;
    }
    Ok(())
}

/// Free a user address space's private frames (the user pages and their page tables).
pub fn free_user(l4: u64, frames: &[u64]) {
    with(|m| unsafe {
        for &f in frames {
            m.frames.deallocate_frame(PhysFrame::containing_address(PhysAddr::new(f)));
        }
        // Page-table pages below the user L4 slots (kernel slots are shared and never freed here).
        let table = &mut *(phys_to_virt(l4) as *mut PageTable);
        let kernel = m.mapper.level_4_table();
        for i in 0..256 {
            if !table[i].is_unused() && kernel[i].is_unused() {
                free_tables(&mut m.frames, table[i].addr().as_u64(), 3);
            }
        }
        m.frames.deallocate_frame(PhysFrame::containing_address(PhysAddr::new(l4)));
    });
}

unsafe fn free_tables(frames: &mut BootInfoFrameAllocator, table: u64, level: u8) {
    if level > 1 {
        let t = &*(phys_to_virt(table) as *const PageTable);
        for e in t.iter() {
            if !e.is_unused() {
                free_tables(frames, e.addr().as_u64(), level - 1);
            }
        }
    }
    frames.deallocate_frame(PhysFrame::containing_address(PhysAddr::new(table)));
}
