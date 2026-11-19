//! StoaFS: Stoa's own on-disk filesystem.
//!
//! Layout (512-byte sectors):
//!   sector 0        superblock: "STOAFS01", version, disk size, directory size, data start
//!   sectors 1..=16  directory: 128 entries x 64 bytes (name, first sector, length, flags)
//!   sectors 17..    file data, each file in one contiguous extent (first-fit allocation)
//!
//! Files are cached in memory and written through to disk on every change. Without a usable disk
//! (or on a disk that holds anything else) StoaFS keeps working in memory only and says so.
use crate::ata::{self, Disk, SECTOR};
use alloc::collections::BTreeMap;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;
use spin::Mutex;

const MAGIC: &[u8; 8] = b"STOAFS01";
const DIR_SECTORS: u64 = 16;
const ENTRY: usize = 64;
const ENTRIES: usize = (DIR_SECTORS as usize * SECTOR) / ENTRY; // 128
const DATA_START: u64 = 1 + DIR_SECTORS;
const NAME_MAX: usize = 47;

#[derive(Clone)]
struct Entry {
    name: String,
    start: u64,
    len: u64,
}

struct Fs {
    files: BTreeMap<String, String>,
    dir: Vec<Entry>, // on-disk directory (persistent mode)
    disk: Option<Disk>,
}

static FS: Mutex<Fs> = Mutex::new(Fs { files: BTreeMap::new(), dir: Vec::new(), disk: None });

fn defaults() -> Vec<(&'static str, &'static str)> {
    vec![
        (
            "readme.txt",
            "Welcome to Stoa!\n\nStoa is a hobby operating system written from scratch in Rust.\n\
It boots on bare x86_64 hardware (or QEMU), sets up its own GDT, IDT,\npaging and heap, drives PCI, \
ATA disks, the PS/2 keyboard and mouse,\nruns preemptive tasks and ring-3 programs, and renders this \
desktop\ninto a linear framebuffer.\n\nFiles you save here are kept on disk (StoaFS).\nTry the Terminal: type 'help'.",
        ),
        (
            "roadmap.txt",
            "Stoa roadmap\n\n[x] Boot + framebuffer\n[x] Interrupts, PIC, PIT\n[x] Paging + heap\n\
[x] Keyboard + mouse\n[x] Window manager + apps\n[x] PCI enumeration\n[x] ATA disk driver + StoaFS\n\
[x] Preemptive scheduler\n[x] User mode + syscalls + ELF loader\n[x] Network card + DHCP\n\
[ ] AHCI/NVMe + USB\n[ ] TCP + a web client\n[ ] SMP (all CPU cores)",
        ),
        ("hello.txt", "Hello from StoaFS."),
    ]
}

impl Fs {
    fn superblock(sectors: u64) -> Vec<u8> {
        let mut s = vec![0u8; SECTOR];
        s[0..8].copy_from_slice(MAGIC);
        s[8..12].copy_from_slice(&1u32.to_le_bytes());
        s[12..20].copy_from_slice(&sectors.to_le_bytes());
        s[20..24].copy_from_slice(&(DIR_SECTORS as u32).to_le_bytes());
        s[24..32].copy_from_slice(&DATA_START.to_le_bytes());
        s
    }

    fn save_dir(&self) -> Result<(), &'static str> {
        let Some(d) = &self.disk else { return Ok(()) };
        let mut buf = vec![0u8; DIR_SECTORS as usize * SECTOR];
        for (i, e) in self.dir.iter().enumerate() {
            let o = i * ENTRY;
            let n = e.name.as_bytes();
            buf[o..o + n.len()].copy_from_slice(n);
            buf[o + 48..o + 56].copy_from_slice(&e.start.to_le_bytes());
            buf[o + 56..o + 64].copy_from_slice(&e.len.to_le_bytes());
        }
        d.write(1, &buf)
    }

    fn load(&mut self) -> Result<(), &'static str> {
        let d = self.disk.clone().ok_or("no disk")?;
        let mut buf = vec![0u8; DIR_SECTORS as usize * SECTOR];
        d.read(1, &mut buf)?;
        for i in 0..ENTRIES {
            let o = i * ENTRY;
            if buf[o] == 0 {
                continue;
            }
            let end = buf[o..o + 48].iter().position(|&b| b == 0).unwrap_or(48);
            let name = String::from_utf8_lossy(&buf[o..o + end]).into_owned();
            let start = u64::from_le_bytes(buf[o + 48..o + 56].try_into().unwrap());
            let len = u64::from_le_bytes(buf[o + 56..o + 64].try_into().unwrap());
            let mut data = vec![0u8; (len as usize).div_ceil(SECTOR) * SECTOR];
            d.read(start, &mut data)?;
            data.truncate(len as usize);
            self.files.insert(name.clone(), String::from_utf8_lossy(&data).into_owned());
            self.dir.push(Entry { name, start, len });
        }
        Ok(())
    }

    /// First free run of `n` sectors in the data area.
    fn allocate(&self, n: u64) -> Option<u64> {
        let total = self.disk.as_ref()?.sectors;
        let mut used: Vec<(u64, u64)> =
            self.dir.iter().map(|e| (e.start, e.start + (e.len as usize).div_ceil(SECTOR).max(1) as u64)).collect();
        used.sort();
        let mut at = DATA_START;
        for (s, e) in used {
            if s >= at + n {
                break;
            }
            at = at.max(e);
        }
        (at + n <= total).then_some(at)
    }

    fn persist(&mut self, name: &str, data: &str) -> Result<(), &'static str> {
        if self.disk.is_none() {
            return Ok(());
        }
        self.dir.retain(|e| e.name != name);
        if self.dir.len() >= ENTRIES {
            return Err("directory full");
        }
        let bytes = data.as_bytes();
        let n = bytes.len().div_ceil(SECTOR).max(1) as u64;
        let start = self.allocate(n).ok_or("disk full")?;
        let mut buf = vec![0u8; n as usize * SECTOR];
        buf[..bytes.len()].copy_from_slice(bytes);
        self.disk.as_ref().unwrap().write(start, &buf)?;
        self.dir.push(Entry { name: name.to_string(), start, len: bytes.len() as u64 });
        self.save_dir()
    }
}

/// Use the first disk that already holds StoaFS, or format the first completely blank one.
/// Disks with anything else on them (like the boot disk) are never touched.
pub fn init() {
    let mut fs = FS.lock();
    let mut blank: Option<Disk> = None;
    for d in ata::disks() {
        let mut s0 = vec![0u8; SECTOR];
        if d.read(0, &mut s0).is_err() {
            continue;
        }
        if &s0[0..8] == MAGIC {
            fs.disk = Some(d.clone());
            match fs.load() {
                Ok(()) => {
                    crate::klog!("stoafs: mounted ata{} ({} files)", d.id, fs.files.len());
                    return;
                }
                Err(e) => {
                    crate::klog!("stoafs: ata{} unreadable: {}", d.id, e);
                    fs.disk = None;
                    fs.dir.clear();
                    fs.files.clear();
                }
            }
        } else if blank.is_none() && d.sectors > DATA_START + 64 {
            let mut probe = vec![0u8; SECTOR * 32];
            if d.read(0, &mut probe).is_ok() && probe.iter().all(|&b| b == 0) {
                blank = Some(d.clone());
            }
        }
    }
    if let Some(d) = blank {
        let ok = d.write(0, &Fs::superblock(d.sectors)).is_ok();
        fs.disk = ok.then_some(d.clone());
        if ok && fs.save_dir().is_ok() {
            crate::klog!("stoafs: formatted blank disk ata{} ({})", d.id, d.model);
            for (n, c) in defaults() {
                fs.files.insert(n.into(), c.into());
                let _ = fs.persist(n, c);
            }
            return;
        }
        fs.disk = None;
    }
    crate::klog!("stoafs: no data disk - files are kept in memory only");
    for (n, c) in defaults() {
        fs.files.insert(n.into(), c.into());
    }
}

pub fn status() -> String {
    let fs = FS.lock();
    match &fs.disk {
        Some(d) => {
            let used: u64 = fs.dir.iter().map(|e| e.len).sum();
            alloc::format!(
                "StoaFS on ata{} ({}): {} files, {} used of {}",
                d.id,
                d.model,
                fs.dir.len(),
                crate::sys::human_bytes(used),
                crate::sys::human_bytes(d.sectors * SECTOR as u64)
            )
        }
        None => String::from("StoaFS in memory (no data disk attached) - changes are lost at shutdown"),
    }
}

pub fn persistent() -> bool {
    FS.lock().disk.is_some()
}

pub fn list() -> Vec<(String, usize)> {
    FS.lock().files.iter().map(|(k, v)| (k.clone(), v.len())).collect()
}
pub fn read(name: &str) -> Option<String> {
    FS.lock().files.get(name).cloned()
}
pub fn write(name: &str, data: &str) {
    let name: String = name.chars().take(NAME_MAX).collect();
    let mut fs = FS.lock();
    fs.files.insert(name.clone(), data.to_string());
    if let Err(e) = fs.persist(&name, data) {
        crate::klog!("stoafs: couldn't save {}: {}", name, e);
    }
}
pub fn remove(name: &str) -> bool {
    let mut fs = FS.lock();
    let had = fs.files.remove(name).is_some();
    if had && fs.disk.is_some() {
        fs.dir.retain(|e| e.name != name);
        let _ = fs.save_dir();
    }
    had
}
pub fn exists(name: &str) -> bool {
    FS.lock().files.contains_key(name)
}
