# Stoa kernel

Stoa boots its own kernel: **Linux 7.0, built by Stoa** from Ubuntu's security-maintained hardware-enablement
(HWE) kernel source for 24.04 - the kernel of Ubuntu 26.04 LTS - with Stoa's configuration, identity and
boot logo.

```
$ uname -r
7.0.14-43-stoa
```

## What's different from Ubuntu's kernel

| | Stoa | Why |
|---|---|---|
| Version | 7.0 (Ubuntu 24.04 ships 6.8) | Newer GPUs (Intel Xe/Arc, AMD RDNA 4), Wi-Fi 7, recent laptops and power management |
| Preemption | Full (`CONFIG_PREEMPT=y`) | The desktop stays responsive under heavy load |
| NTSYNC | Built in (`/dev/ntsync`) | Windows' synchronisation primitives in the kernel: Wine and Proton games run faster and smoother |
| Memory | Multi-generational LRU on, zram swap (zstd) | Old PCs with 4-8 GB stay responsive when memory is tight |
| Network | BBR + fq by default | Faster, steadier downloads, streaming and video calls |
| Timer | 1000 Hz | Smoother input, audio and animations |
| Debug info | None | Smaller packages, faster boots and builds |
| Module signing | Stoa's own build key | Ubuntu's certificates aren't ours |
| Boot logo | Stoa emblem | Shown on the console during verbose boots |
| Identity | `-stoa` release name, built by `stoa@stoa-os` | It's our kernel |

Everything else comes from Ubuntu's generic configuration for that kernel, so hardware support matches
Ubuntu 26.04: Wi-Fi, GPUs, VirtualBox/VMware/Hyper-V/QEMU guests, laptops, USB devices. Rust-written drivers
are left out (they need a matching Rust toolchain at build time). The OS side adds zram swap
(`/etc/systemd/zram-generator.conf`), matching `sysctl` settings and the Stoa boot screen (Plymouth theme
`stoa`, also used for the disk-encryption prompt).

The full configuration change is [`stoa.config`](stoa.config); edit it to tune the kernel.

## How it's built and updated

- `.github/workflows/kernel.yml` runs **every Monday**: if Ubuntu has published a new kernel source (they do
  so for every security fix), it builds a new Stoa kernel and publishes it as a `kernel-<version>`
  GitHub release. It also runs whenever `kernel/` changes, or on demand from the Actions tab.
- The ISO workflow then rebuilds the ISO with the newest Stoa kernel.
- On an installed system the Stoa kernel boots by default (its version, `7.0.0-…`, sorts above
  Ubuntu's `6.8.0-…`). Ubuntu's generic kernel stays installed as a fallback under **Advanced options**
  in the boot menu, and keeps receiving Ubuntu's security updates.
- To build from Ubuntu's original 24.04 kernel (6.8) instead, set `SRC_PKG: linux` in the workflow.

> **Updates on installed PCs:** new Stoa kernels reach installed systems once Stoa has a public
> package repository (planned). Until then, reinstall from a new ISO or install the release's
> `linux-image-*.deb` with `stoa install`.

## Build it yourself

```bash
# Ubuntu 24.04, with deb-src enabled for noble, noble-updates and noble-security
sudo apt install build-essential bc bison flex libssl-dev libelf-dev dwarves rsync cpio kmod zstd dpkg-dev debhelper python3-pil libdw-dev
./build-kernel.sh                          # latest linux-hwe-7.0 source
./build-kernel.sh 7.0.0-43.43~24.04.1      # or a specific one
CONFIG_ONLY=1 ./build-kernel.sh            # just produce and check the merged config
ls out/                           # linux-image-…-stoa_….deb, linux-headers-…
```

Takes about 1–2 hours on 4 cores. To put it in an ISO, copy `out/linux-image-*.deb` to `linux/kernel-debs/`
and run `sudo linux/build-iso.sh`.

## The research kernel

[`research/`](../research) is a separate, from-scratch kernel written in Rust - our long-term
experiment in a kernel designed entirely by Stoa. The Stoa kernel above is what ships, because
it runs real hardware and real software today.
