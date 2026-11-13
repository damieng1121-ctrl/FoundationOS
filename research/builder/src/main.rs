//! Usage: foundation-builder <kernel-elf> <out-dir>
use std::path::PathBuf;

fn main() {
    let mut args = std::env::args().skip(1);
    let kernel = PathBuf::from(args.next().expect("usage: foundation-builder <kernel-elf> <out-dir>"));
    let out = PathBuf::from(args.next().unwrap_or_else(|| "target".into()));
    std::fs::create_dir_all(&out).expect("create output dir");

    // Ask for at least 1280x720 and keep the screen clean (boot log goes to serial only).
    let mut cfg = bootloader::BootConfig::default();
    cfg.frame_buffer.minimum_framebuffer_width = Some(1280);
    cfg.frame_buffer.minimum_framebuffer_height = Some(720);
    cfg.frame_buffer_logging = false;

    let bios = out.join("foundation-bios.img");
    bootloader::BiosBoot::new(&kernel).set_boot_config(&cfg).create_disk_image(&bios).expect("BIOS image");
    println!("BIOS image: {}", bios.display());

    let uefi = out.join("foundation-uefi.img");
    bootloader::UefiBoot::new(&kernel).set_boot_config(&cfg).create_disk_image(&uefi).expect("UEFI image");
    println!("UEFI image: {}", uefi.display());
}
