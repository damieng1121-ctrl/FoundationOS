//! ATA (IDE) disk driver: PIO mode, 28-bit LBA, polling. Finds every disk on the two legacy channels.
use alloc::string::String;
use alloc::vec::Vec;
use spin::Mutex;
use x86_64::instructions::port::Port;

pub const SECTOR: usize = 512;

#[derive(Clone, Debug)]
pub struct Disk {
    pub id: usize,
    base: u16,
    ctrl: u16,
    slave: bool,
    pub sectors: u64,
    pub model: String,
}

static DISKS: Mutex<Vec<Disk>> = Mutex::new(Vec::new());

unsafe fn inb(p: u16) -> u8 {
    Port::<u8>::new(p).read()
}
unsafe fn outb(p: u16, v: u8) {
    Port::<u8>::new(p).write(v)
}

impl Disk {
    fn status(&self) -> u8 {
        unsafe { inb(self.base + 7) }
    }
    /// 400 ns delay by reading the alternate status port four times.
    fn delay(&self) {
        for _ in 0..4 {
            unsafe { inb(self.ctrl) };
        }
    }
    fn wait_ready(&self) -> Result<(), &'static str> {
        for _ in 0..1_000_000 {
            let s = self.status();
            if s & 0x80 == 0 {
                if s & 0x21 != 0 {
                    return Err("disk error");
                }
                return Ok(());
            }
        }
        Err("disk timeout")
    }
    fn wait_drq(&self) -> Result<(), &'static str> {
        for _ in 0..1_000_000 {
            let s = self.status();
            if s & 0x80 == 0 {
                if s & 0x21 != 0 {
                    return Err("disk error");
                }
                if s & 0x08 != 0 {
                    return Ok(());
                }
            }
        }
        Err("disk timeout")
    }
    fn select(&self, lba: u64, count: u8) -> Result<(), &'static str> {
        if lba + count as u64 > self.sectors.min(1 << 28) {
            return Err("sector out of range");
        }
        self.wait_ready()?;
        unsafe {
            outb(self.base + 6, 0xE0 | (self.slave as u8) << 4 | ((lba >> 24) & 0x0F) as u8);
            self.delay();
            outb(self.base + 2, count);
            outb(self.base + 3, lba as u8);
            outb(self.base + 4, (lba >> 8) as u8);
            outb(self.base + 5, (lba >> 16) as u8);
        }
        Ok(())
    }

    pub fn read(&self, lba: u64, buf: &mut [u8]) -> Result<(), &'static str> {
        let count = buf.len() / SECTOR;
        for (i, chunk) in buf.chunks_mut(SECTOR).enumerate().take(count) {
            x86_64::instructions::interrupts::without_interrupts(|| -> Result<(), &'static str> {
                self.select(lba + i as u64, 1)?;
                unsafe { outb(self.base + 7, 0x20) }; // READ SECTORS
                self.delay();
                self.wait_drq()?;
                let mut data = Port::<u16>::new(self.base);
                for w in chunk.chunks_mut(2) {
                    let v = unsafe { data.read() };
                    w[0] = v as u8;
                    w[1] = (v >> 8) as u8;
                }
                Ok(())
            })?;
        }
        Ok(())
    }

    pub fn write(&self, lba: u64, buf: &[u8]) -> Result<(), &'static str> {
        for (i, chunk) in buf.chunks(SECTOR).enumerate() {
            x86_64::instructions::interrupts::without_interrupts(|| -> Result<(), &'static str> {
                self.select(lba + i as u64, 1)?;
                unsafe { outb(self.base + 7, 0x30) }; // WRITE SECTORS
                self.delay();
                self.wait_drq()?;
                let mut data = Port::<u16>::new(self.base);
                for w in chunk.chunks(2) {
                    unsafe { data.write(w[0] as u16 | (*w.get(1).unwrap_or(&0) as u16) << 8) };
                }
                Ok(())
            })?;
        }
        x86_64::instructions::interrupts::without_interrupts(|| -> Result<(), &'static str> {
            self.wait_ready()?;
            unsafe { outb(self.base + 7, 0xE7) }; // CACHE FLUSH
            self.delay();
            self.wait_ready()
        })
    }
}

fn identify(id: usize, base: u16, ctrl: u16, slave: bool) -> Option<Disk> {
    unsafe {
        if inb(base + 7) == 0xFF {
            return None; // floating bus: no controller
        }
        outb(base + 6, 0xA0 | (slave as u8) << 4);
        for _ in 0..4 {
            inb(ctrl);
        }
        outb(base + 2, 0);
        outb(base + 3, 0);
        outb(base + 4, 0);
        outb(base + 5, 0);
        outb(base + 7, 0xEC); // IDENTIFY
        if inb(base + 7) == 0 {
            return None;
        }
        let mut n = 0;
        while inb(base + 7) & 0x80 != 0 {
            n += 1;
            if n > 1_000_000 {
                return None;
            }
        }
        if inb(base + 4) != 0 || inb(base + 5) != 0 {
            return None; // ATAPI (CD-ROM) or SATA signature: not an ATA disk
        }
        loop {
            let s = inb(base + 7);
            if s & 0x01 != 0 {
                return None;
            }
            if s & 0x08 != 0 {
                break;
            }
        }
        let mut words = [0u16; 256];
        let mut data = Port::<u16>::new(base);
        for w in words.iter_mut() {
            *w = data.read();
        }
        let sectors = words[60] as u64 | (words[61] as u64) << 16;
        let mut model = String::new();
        for w in &words[27..47] {
            model.push((w >> 8) as u8 as char);
            model.push(*w as u8 as char);
        }
        Some(Disk { id, base, ctrl, slave, sectors, model: String::from(model.trim()) })
    }
}

pub fn init() {
    let mut disks = Vec::new();
    for (base, ctrl) in [(0x1F0u16, 0x3F6u16), (0x170, 0x376)] {
        for slave in [false, true] {
            if let Some(d) = identify(disks.len(), base, ctrl, slave) {
                crate::klog!(
                    "ata{}: {} ({}) on {:#x}{}",
                    d.id,
                    d.model,
                    crate::sys::human_bytes(d.sectors * SECTOR as u64),
                    base,
                    if slave { " slave" } else { "" }
                );
                disks.push(d);
            }
        }
    }
    *DISKS.lock() = disks;
}

pub fn disks() -> Vec<Disk> {
    DISKS.lock().clone()
}
