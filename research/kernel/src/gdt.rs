//! Global Descriptor Table and Task State Segment.
//!
//! Kernel code/data (ring 0), user code/data (ring 3) and the TSS, whose RSP0 is switched to the running
//! task's kernel stack so interrupts and system calls from user programs land on that task's own stack.
use spin::Once;
use x86_64::instructions::segmentation::{Segment, CS, DS, ES, SS};
use x86_64::instructions::tables::load_tss;
use x86_64::structures::gdt::{Descriptor, GlobalDescriptorTable, SegmentSelector};
use x86_64::structures::tss::TaskStateSegment;
use x86_64::VirtAddr;

pub const DOUBLE_FAULT_IST_INDEX: u16 = 0;
const IST_STACK_SIZE: usize = 4096 * 5;
static mut DOUBLE_FAULT_STACK: [u8; IST_STACK_SIZE] = [0; IST_STACK_SIZE];
static mut TSS: TaskStateSegment = TaskStateSegment::new();

pub struct Selectors {
    pub kernel_code: SegmentSelector,
    pub kernel_data: SegmentSelector,
    pub user_code: SegmentSelector,
    pub user_data: SegmentSelector,
    tss: SegmentSelector,
}

static GDT: Once<(GlobalDescriptorTable, Selectors)> = Once::new();

pub fn init() {
    let tss: &'static TaskStateSegment = unsafe {
        let start = VirtAddr::from_ptr(&raw const DOUBLE_FAULT_STACK);
        (*(&raw mut TSS)).interrupt_stack_table[DOUBLE_FAULT_IST_INDEX as usize] = start + IST_STACK_SIZE as u64;
        &*(&raw const TSS)
    };
    let (gdt, sel) = GDT.call_once(|| {
        let mut gdt = GlobalDescriptorTable::new();
        let kernel_code = gdt.append(Descriptor::kernel_code_segment());
        let kernel_data = gdt.append(Descriptor::kernel_data_segment());
        let user_data = gdt.append(Descriptor::user_data_segment());
        let user_code = gdt.append(Descriptor::user_code_segment());
        let tss = gdt.append(Descriptor::tss_segment(tss));
        (gdt, Selectors { kernel_code, kernel_data, user_code, user_data, tss })
    });
    gdt.load();
    unsafe {
        CS::set_reg(sel.kernel_code);
        DS::set_reg(sel.kernel_data);
        ES::set_reg(sel.kernel_data);
        SS::set_reg(sel.kernel_data);
        load_tss(sel.tss);
    }
}

pub fn selectors() -> &'static Selectors {
    &GDT.get().expect("GDT not loaded").1
}

/// Stack the CPU switches to when an interrupt or system call arrives from ring 3.
pub fn set_kernel_stack(top: u64) {
    unsafe { (*(&raw mut TSS)).privilege_stack_table[0] = VirtAddr::new(top) };
}
