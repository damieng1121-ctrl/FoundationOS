//! Intel 8254x (e1000) Ethernet driver: memory-mapped registers, DMA descriptor rings, polled receive.
//! QEMU's default network card, also found in VirtualBox and many older Intel desktops.
use crate::{memory, pci};
use alloc::vec::Vec;
use core::ptr::{read_volatile, write_volatile};
use spin::Mutex;

const CTRL: u32 = 0x0000;
const STATUS: u32 = 0x0008;
const IMC: u32 = 0x00D8;
const RCTL: u32 = 0x0100;
const TCTL: u32 = 0x0400;
const TIPG: u32 = 0x0410;
const RDBAL: u32 = 0x2800;
const RDBAH: u32 = 0x2804;
const RDLEN: u32 = 0x2808;
const RDH: u32 = 0x2810;
const RDT: u32 = 0x2818;
const TDBAL: u32 = 0x3800;
const TDBAH: u32 = 0x3804;
const TDLEN: u32 = 0x3808;
const TDH: u32 = 0x3810;
const TDT: u32 = 0x3818;
const MTA: u32 = 0x5200;
const RAL: u32 = 0x5400;
const RAH: u32 = 0x5404;

const RX_COUNT: usize = 32;
const TX_COUNT: usize = 16;
const BUF: usize = 2048;

#[repr(C)]
#[derive(Clone, Copy)]
struct RxDesc {
    addr: u64,
    len: u16,
    csum: u16,
    status: u8,
    errors: u8,
    special: u16,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct TxDesc {
    addr: u64,
    len: u16,
    cso: u8,
    cmd: u8,
    status: u8,
    css: u8,
    special: u16,
}

pub struct E1000 {
    regs: u64,
    pub mac: [u8; 6],
    rx: u64, // virtual address of the RX ring
    tx: u64,
    rx_bufs: Vec<u64>, // physical addresses
    tx_bufs: Vec<u64>,
    rx_next: usize,
    tx_next: usize,
    pub rx_packets: u64,
    pub tx_packets: u64,
}

pub static NIC: Mutex<Option<E1000>> = Mutex::new(None);

impl E1000 {
    fn r(&self, reg: u32) -> u32 {
        unsafe { read_volatile((self.regs + reg as u64) as *const u32) }
    }
    fn w(&self, reg: u32, v: u32) {
        unsafe { write_volatile((self.regs + reg as u64) as *mut u32, v) }
    }

    pub fn link_up(&self) -> bool {
        self.r(STATUS) & 2 != 0
    }

    pub fn send(&mut self, frame: &[u8]) -> bool {
        if frame.len() > BUF {
            return false;
        }
        let i = self.tx_next;
        let d = unsafe { &mut *((self.tx + (i * 16) as u64) as *mut TxDesc) };
        // A descriptor is free once the card has written it back (DD) - or was never used.
        if d.cmd != 0 && unsafe { read_volatile(&d.status) } & 1 == 0 {
            return false;
        }
        unsafe {
            core::ptr::copy_nonoverlapping(frame.as_ptr(), memory::phys_to_virt(self.tx_bufs[i]) as *mut u8, frame.len())
        };
        d.addr = self.tx_bufs[i];
        d.len = frame.len().max(60) as u16; // the card pads short frames to the Ethernet minimum
        d.cso = 0;
        d.cmd = 0b1011; // EOP | IFCS | RS
        unsafe { write_volatile(&mut d.status, 0) };
        self.tx_next = (i + 1) % TX_COUNT;
        self.w(TDT, self.tx_next as u32);
        self.tx_packets += 1;
        true
    }

    pub fn receive(&mut self) -> Option<Vec<u8>> {
        let i = self.rx_next;
        let d = unsafe { &mut *((self.rx + (i * 16) as u64) as *mut RxDesc) };
        if unsafe { read_volatile(&d.status) } & 1 == 0 {
            return None;
        }
        let len = d.len as usize;
        let data = unsafe {
            core::slice::from_raw_parts(memory::phys_to_virt(self.rx_bufs[i]) as *const u8, len.min(BUF))
        }
        .to_vec();
        unsafe { write_volatile(&mut d.status, 0) };
        self.w(RDT, i as u32); // hand the descriptor back to the card
        self.rx_next = (i + 1) % RX_COUNT;
        self.rx_packets += 1;
        Some(data)
    }
}

/// Find and start the first supported Intel card. Returns its MAC address.
pub fn init() -> Option<[u8; 6]> {
    const IDS: [u16; 6] = [0x100E, 0x100F, 0x10D3, 0x1004, 0x107C, 0x153A];
    let dev = pci::devices().into_iter().find(|d| d.vendor == 0x8086 && IDS.contains(&d.device))?;
    dev.enable();
    let bar0 = dev.bar(0);
    if bar0 & 1 != 0 {
        crate::klog!("e1000: BAR0 is I/O space - unsupported");
        return None;
    }
    let mut phys = (bar0 & !0xF) as u64;
    if (bar0 >> 1) & 3 == 2 {
        phys |= (dev.bar(1) as u64) << 32;
    }
    let regs = memory::map_mmio(phys, 128 * 1024);
    let rx_ring = memory::alloc_frame()?;
    let tx_ring = memory::alloc_frame()?;
    let mut rx_bufs = Vec::new();
    for _ in 0..RX_COUNT / 2 {
        let f = memory::alloc_frame()?;
        rx_bufs.push(f);
        rx_bufs.push(f + BUF as u64);
    }
    let mut tx_bufs = Vec::new();
    for _ in 0..TX_COUNT / 2 {
        let f = memory::alloc_frame()?;
        tx_bufs.push(f);
        tx_bufs.push(f + BUF as u64);
    }
    let mut nic = E1000 {
        regs,
        mac: [0; 6],
        rx: memory::phys_to_virt(rx_ring),
        tx: memory::phys_to_virt(tx_ring),
        rx_bufs,
        tx_bufs,
        rx_next: 0,
        tx_next: 0,
        rx_packets: 0,
        tx_packets: 0,
    };

    nic.w(IMC, 0xFFFF_FFFF); // we poll; no interrupts
    nic.w(CTRL, nic.r(CTRL) | 1 << 26); // reset
    for _ in 0..100_000 {
        if nic.r(CTRL) & 1 << 26 == 0 {
            break;
        }
    }
    nic.w(IMC, 0xFFFF_FFFF);
    nic.w(CTRL, (nic.r(CTRL) | 1 << 6 | 1 << 5) & !(1 << 3)); // set link up, auto speed; clear link reset

    let (lo, hi) = (nic.r(RAL), nic.r(RAH));
    nic.mac = [lo as u8, (lo >> 8) as u8, (lo >> 16) as u8, (lo >> 24) as u8, hi as u8, (hi >> 8) as u8];
    nic.w(RAH, hi | 1 << 31); // address valid
    for i in 0..128 {
        nic.w(MTA + i * 4, 0);
    }

    for i in 0..RX_COUNT {
        let d = unsafe { &mut *((nic.rx + (i * 16) as u64) as *mut RxDesc) };
        *d = RxDesc { addr: nic.rx_bufs[i], len: 0, csum: 0, status: 0, errors: 0, special: 0 };
    }
    nic.w(RDBAL, rx_ring as u32);
    nic.w(RDBAH, (rx_ring >> 32) as u32);
    nic.w(RDLEN, (RX_COUNT * 16) as u32);
    nic.w(RDH, 0);
    nic.w(RDT, (RX_COUNT - 1) as u32);
    // Enable, accept broadcast, strip CRC, 2 KiB buffers.
    nic.w(RCTL, 1 << 1 | 1 << 15 | 1 << 26);

    nic.w(TDBAL, tx_ring as u32);
    nic.w(TDBAH, (tx_ring >> 32) as u32);
    nic.w(TDLEN, (TX_COUNT * 16) as u32);
    nic.w(TDH, 0);
    nic.w(TDT, 0);
    nic.w(TCTL, 1 << 1 | 1 << 3 | 0x10 << 4 | 0x40 << 12); // enable, pad short packets, collision settings
    nic.w(TIPG, 0x0060_200A);

    let mac = nic.mac;
    crate::klog!(
        "e1000: {:04x} at {:#x}, MAC {:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}, link {}",
        dev.device, phys, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5],
        if nic.link_up() { "up" } else { "down" }
    );
    *NIC.lock() = Some(nic);
    Some(mac)
}
