# Stoa

**The computer that builds what you need.**

A *stoa* was the covered colonnade at the heart of an ancient Greek city: a public place built to serve the
people inside it, where they met, traded and learned (the Stoic philosophers took their name from one in
Athens). Stoa the operating system has the same aim: a calm, trustworthy computer that works for the person
using it, and builds what they need when they ask.

Stoa has three tracks:

| Track | What it is | Status |
|---|---|---|
| **[Stoa](linux/)** (`linux/`) | The everyday OS: Stoa desktop, store, package manager and installer on the Linux kernel (Ubuntu 24.04 LTS base). Runs Chrome, Microsoft 365, Google Drive, Flatpak apps and Windows `.exe`/`.msi` programs. | v0.2, installable ISO |
| **[Stoa kernel](kernel/)** (`kernel/`) | Stoa's own Linux kernel build: desktop-tuned (full preemption, 1000 Hz), Stoa identity and boot logo, rebuilt weekly from Ubuntu's security-maintained source. | Default kernel of Stoa |
| **[Research kernel](research/)** (`research/`) | A from-scratch x86_64 kernel and GUI written in Rust - our own kernel, window manager and apps. | v0.1, boots in QEMU |

## Stoa (installable)

- **Bootable ISO** with a live session and a graphical installer (Calamares): BIOS + UEFI, ext4/btrfs/xfs, full-disk or manual partitioning.
- **Stoa desktop**: labwc compositor, the Stoa bar and Stoa menu, Stoa Store, Settings, welcome app.
- **`fpkg`**, one package manager for everything:
  - `stoa install google-chrome` / `microsoft-365` / `google-drive` / `zoom` / ... (39-app catalog: vendor apt repos, Flathub, web apps)
  - `stoa install setup.exe` / `installer.msi` - Windows programs, each in its own Wine "bottle", added to the menu
  - `stoa pack setup.exe --name "My App" --args /S` - wrap any Windows installer as a `.fpkg` Stoa package
  - `stoa install app.fpkg | file.deb | App.AppImage | flatpak:<id>`
  - `stoa update` - OS, apps, Flatpaks and Stoa packages; security updates also install automatically
- **Networking**: NetworkManager (Ethernet, Wi-Fi, VPN), Bluetooth, PipeWire audio.
- **VM friendly**: guest tools for QEMU/KVM, VirtualBox and VMware.

See **[linux/README.md](linux/README.md)** for downloading the ISO, testing it in a VM and building it yourself.

## Research kernel

![Stoa research kernel desktop](docs/desktop-paint.png)

### What's in v0.1 "Bedrock"

**Kernel** (`research/kernel/`, `no_std` Rust)
- Boots via BIOS or UEFI (the [`bootloader`](https://crates.io/crates/bootloader) crate) into a linear framebuffer
- GDT + TSS with a dedicated double-fault stack, IDT with exception handlers
- 8259 PIC + PIT timer at 100 Hz, CMOS real-time clock
- 4-level paging, physical frame allocator, 48 MiB kernel heap
- PS/2 keyboard and mouse drivers (lock-free IRQ → main-loop queues)
- Serial console logging (COM1) and an in-memory kernel log (`dmesg`)
- StoaFS: a flat in-memory filesystem

**Desktop shell**
- Compositing window manager: drag, focus, minimise, close, drop shadows
- Taskbar with window list and live clock, start menu with restart/shut down
- Desktop icons, anti-aliased text (Noto Sans Mono)

**Apps:** Terminal (20+ commands: `ls`, `cat`, `write`, `edit`, `open`, `neofetch`, `calc`, `dmesg`, ...), Files, Editor, Paint, Clock, System Monitor, About.

| Start menu | Multitasking |
|---|---|
| ![](docs/start-menu.png) | ![](docs/many-windows.png) |

### Build and run

Requirements: [rustup](https://rustup.rs) (the pinned nightly toolchain installs automatically) and QEMU.

```bash
cd research
./run.sh          # build + boot in QEMU (BIOS)
./run.sh --uefi   # boot via OVMF instead
./build.sh        # only build target/stoa-{bios,uefi}.img
```

The disk images can also be written to a USB stick and booted on real hardware that supports PS/2 emulation (most PCs do for USB keyboards/mice via legacy mode).

### Layout

```
research/kernel/src/
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
  fs.rs           StoaFS (in memory)
  sys.rs          system state, power, CPU info
research/builder/ turns the kernel ELF into bootable disk images
```

### Roadmap

- [ ] Preemptive scheduler and processes
- [ ] User mode + system calls, ELF loader
- [ ] AHCI/NVMe storage + persistent on-disk filesystem, installer
- [ ] Networking (virtio-net / e1000 + TCP/IP)
- [ ] Package format, app store and updates
