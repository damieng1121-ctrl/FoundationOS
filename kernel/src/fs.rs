//! FoundationFS: a tiny flat in-memory filesystem.
use alloc::collections::BTreeMap;
use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

static FS: Mutex<BTreeMap<String, String>> = Mutex::new(BTreeMap::new());

pub fn init() {
    let mut fs = FS.lock();
    fs.insert(
        "readme.txt".into(),
        "Welcome to Foundation OS!\n\nFoundation is a hobby operating system written from scratch in Rust.\n\
It boots on bare x86_64 hardware (or QEMU), sets up its own GDT, IDT,\n\
paging and heap, drives the PS/2 keyboard and mouse, and renders this\n\
desktop into a linear framebuffer.\n\nTry the Terminal: type 'help'."
            .into(),
    );
    fs.insert(
        "roadmap.txt".into(),
        "Foundation roadmap\n\n[x] Boot + framebuffer\n[x] Interrupts, PIC, PIT\n[x] Paging + heap\n\
[x] Keyboard + mouse\n[x] Window manager + apps\n[ ] Preemptive scheduler\n[ ] User mode + syscalls\n\
[ ] Disk driver + persistent filesystem\n[ ] ELF loader\n[ ] Networking"
            .into(),
    );
    fs.insert("hello.txt".into(), "Hello from FoundationFS.".into());
}

pub fn list() -> Vec<(String, usize)> {
    FS.lock().iter().map(|(k, v)| (k.clone(), v.len())).collect()
}
pub fn read(name: &str) -> Option<String> {
    FS.lock().get(name).cloned()
}
pub fn write(name: &str, data: &str) {
    FS.lock().insert(name.to_string(), data.to_string());
}
pub fn remove(name: &str) -> bool {
    FS.lock().remove(name).is_some()
}
pub fn exists(name: &str) -> bool {
    FS.lock().contains_key(name)
}
