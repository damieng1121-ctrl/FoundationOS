# Foundation OS

A hobby operating system written from scratch in Rust for x86_64: our own kernel, our own window manager, our own apps.

![Foundation desktop](docs/desktop-paint.png)

## What's in v0.1 "Bedrock"

**Kernel** (`kernel/`, `no_std` Rust)
- Boots via BIOS or UEFI (the [`bootloader`](https://crates.io/crates/bootloader) crate) into a linear framebuffer
- GDT + TSS with a dedicated double-fault stack, IDT with exception handlers
- 8259 PIC + PIT timer at 100 Hz, CMOS real-time clock
- 4-level paging, physical frame allocator, 48 MiB kernel heap
- PS/2 keyboard and mouse drivers (lock-free IRQ → main-loop queues)
- Serial console logging (COM1) and an in-memory kernel log (`dmesg`)
- FoundationFS: a flat in-memory filesystem

**Desktop shell**
- Compositing window manager: drag, focus, minimise, close, drop shadows
- Taskbar with window list and live clock, start menu with restart/shut down
- Desktop icons, anti-aliased text (Noto Sans Mono)

**Apps:** Terminal (20+ commands: `ls`, `cat`, `write`, `edit`, `open`, `neofetch`, `calc`, `dmesg`, ...), Files, Notepad, Paint, Clock, System Monitor, About.

| Start menu | Multitasking |
|---|---|
| ![](docs/start-menu.png) | ![](docs/many-windows.png) |

## Build and run

Requirements: [rustup](https://rustup.rs) (the pinned nightly toolchain installs automatically) and QEMU.

```bash
./run.sh          # build + boot in QEMU (BIOS)
./run.sh --uefi   # boot via OVMF instead
./build.sh        # only build target/foundation-{bios,uefi}.img
```

The disk images can also be written to a USB stick and booted on real hardware that supports PS/2 emulation (most PCs do for USB keyboards/mice via legacy mode).

## Layout

```
kernel/src/
  main.rs         entry point + main event loop
  gdt.rs          GDT/TSS
  interrupts.rs   IDT, PIC, PIT, IRQ handlers
  memory.rs       paging + frame allocator
  allocator.rs    kernel heap
  mouse.rs        PS/2 mouse
  rtc.rs          CMOS clock
  gfx.rs          canvas, primitives, text, framebuffer output
  wm.rs           window manager, taskbar, start menu
  apps.rs         built-in applications
  fs.rs           FoundationFS (in memory)
  sys.rs          system state, power, CPU info
builder/          turns the kernel ELF into bootable disk images
```

## Roadmap

- [ ] Preemptive scheduler and processes
- [ ] User mode + system calls, ELF loader
- [ ] AHCI/NVMe storage + persistent on-disk filesystem, installer
- [ ] Networking (virtio-net / e1000 + TCP/IP)
- [ ] Package format, app store and updates
