//! Built-in user programs (/bin): ELF executables built from research/user and embedded in the kernel.
pub struct Program {
    pub name: &'static str,
    pub about: &'static str,
    pub elf: &'static [u8],
}

macro_rules! prog {
    ($name:literal, $about:literal) => {
        Program {
            name: $name,
            about: $about,
            elf: include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/../user/target/x86_64-unknown-none/release/", $name)),
        }
    };
}

pub static PROGRAMS: &[Program] = &[
    prog!("hello", "greets you from ring 3"),
    prog!("primes", "counts primes (CPU-heavy; the desktop stays responsive)"),
    prog!("crash", "misbehaves on purpose; the kernel survives"),
];

pub fn find(name: &str) -> Option<&'static Program> {
    PROGRAMS.iter().find(|p| p.name == name)
}
