//! PCI bus enumeration through the legacy configuration ports (0xCF8/0xCFC).
use alloc::string::String;
use alloc::vec::Vec;
use spin::Mutex;
use x86_64::instructions::port::Port;

#[derive(Clone, Copy, Debug)]
pub struct Device {
    pub bus: u8,
    pub slot: u8,
    pub func: u8,
    pub vendor: u16,
    pub device: u16,
    pub class: u8,
    pub subclass: u8,
    pub prog_if: u8,
    pub irq: u8,
}

static DEVICES: Mutex<Vec<Device>> = Mutex::new(Vec::new());

fn addr(bus: u8, slot: u8, func: u8, off: u8) -> u32 {
    0x8000_0000 | (bus as u32) << 16 | (slot as u32) << 11 | (func as u32) << 8 | (off as u32 & 0xFC)
}

pub fn read32(bus: u8, slot: u8, func: u8, off: u8) -> u32 {
    unsafe {
        Port::<u32>::new(0xCF8).write(addr(bus, slot, func, off));
        Port::<u32>::new(0xCFC).read()
    }
}

pub fn write32(bus: u8, slot: u8, func: u8, off: u8, v: u32) {
    unsafe {
        Port::<u32>::new(0xCF8).write(addr(bus, slot, func, off));
        Port::<u32>::new(0xCFC).write(v);
    }
}

impl Device {
    pub fn bar(&self, n: u8) -> u32 {
        read32(self.bus, self.slot, self.func, 0x10 + n * 4)
    }
    /// Turn on I/O space, memory space and bus mastering (needed for DMA).
    pub fn enable(&self) {
        let cmd = read32(self.bus, self.slot, self.func, 0x04);
        write32(self.bus, self.slot, self.func, 0x04, cmd | 0x7);
    }
    pub fn class_name(&self) -> &'static str {
        match (self.class, self.subclass) {
            (0x01, 0x01) => "IDE controller",
            (0x01, 0x06) => "SATA controller",
            (0x01, 0x08) => "NVMe controller",
            (0x01, _) => "Storage controller",
            (0x02, 0x00) => "Ethernet controller",
            (0x02, _) => "Network controller",
            (0x03, 0x00) => "VGA display",
            (0x03, _) => "Display controller",
            (0x04, 0x01) => "Audio device",
            (0x04, 0x03) => "HD Audio",
            (0x04, _) => "Multimedia device",
            (0x06, 0x00) => "Host bridge",
            (0x06, 0x01) => "ISA bridge",
            (0x06, 0x04) => "PCI bridge",
            (0x06, 0x80) => "Bridge",
            (0x06, _) => "Bridge",
            (0x0C, 0x03) => "USB controller",
            (0x0C, 0x05) => "SMBus",
            (0x0C, _) => "Serial bus",
            _ => "Device",
        }
    }
    pub fn vendor_name(&self) -> &'static str {
        match self.vendor {
            0x8086 => "Intel",
            0x1022 => "AMD",
            0x10DE => "NVIDIA",
            0x1002 => "AMD/ATI",
            0x10EC => "Realtek",
            0x14E4 => "Broadcom",
            0x1AF4 => "Red Hat (virtio)",
            0x1234 => "QEMU",
            0x15AD => "VMware",
            0x80EE => "VirtualBox",
            0x1B36 => "Red Hat (QEMU)",
            _ => "Unknown",
        }
    }
    pub fn describe(&self) -> String {
        alloc::format!(
            "{:02x}:{:02x}.{} {:<20} {} [{:04x}:{:04x}]",
            self.bus, self.slot, self.func, self.class_name(), self.vendor_name(), self.vendor, self.device
        )
    }
}

fn probe(bus: u8, slot: u8, func: u8) -> Option<Device> {
    let id = read32(bus, slot, func, 0);
    if id & 0xFFFF == 0xFFFF {
        return None;
    }
    let class = read32(bus, slot, func, 0x08);
    let irq = read32(bus, slot, func, 0x3C) as u8;
    Some(Device {
        bus,
        slot,
        func,
        vendor: id as u16,
        device: (id >> 16) as u16,
        class: (class >> 24) as u8,
        subclass: (class >> 16) as u8,
        prog_if: (class >> 8) as u8,
        irq,
    })
}

/// Brute-force scan of every bus/slot/function (fast enough at boot, and finds devices behind bridges).
pub fn init() {
    let mut found = Vec::new();
    for bus in 0..=255u8 {
        for slot in 0..32u8 {
            let Some(d) = probe(bus, slot, 0) else { continue };
            let multi = (read32(bus, slot, 0, 0x0C) >> 16) & 0x80 != 0;
            found.push(d);
            if multi {
                for func in 1..8 {
                    if let Some(d) = probe(bus, slot, func) {
                        found.push(d);
                    }
                }
            }
        }
    }
    for d in &found {
        crate::klog!("pci {}", d.describe());
    }
    *DEVICES.lock() = found;
}

pub fn devices() -> Vec<Device> {
    DEVICES.lock().clone()
}

pub fn find(vendor: u16, device: u16) -> Option<Device> {
    DEVICES.lock().iter().copied().find(|d| d.vendor == vendor && d.device == device)
}

pub fn find_class(class: u8, subclass: u8) -> Option<Device> {
    DEVICES.lock().iter().copied().find(|d| d.class == class && d.subclass == subclass)
}
