# Foundation kernel

Foundation OS boots its own kernel: **Linux, built by Foundation** from Ubuntu 24.04's security-maintained
kernel source, with Foundation's configuration, identity and boot logo.

```
$ uname -r
6.8.12-149-foundation
```

## What's different from Ubuntu's kernel

| | Foundation | Why |
|---|---|---|
| Preemption | Full (`CONFIG_PREEMPT=y`) | The desktop stays responsive under heavy load |
| Timer | 1000 Hz | Smoother input, audio and animations |
| Debug info | None | Smaller packages, faster boots and builds |
| Module signing | Foundation's own build key | Ubuntu's certificates aren't ours |
| Boot logo | Foundation emblem | Shown on the console during verbose boots |
| Identity | `-foundation` release name, built by `foundation@foundation-os` | It's our kernel |

Everything else comes from Ubuntu's generic configuration, so hardware support is the same: Wi-Fi, GPUs,
VirtualBox/VMware/Hyper-V/QEMU guests, laptops, USB devices.

The full configuration change is [`foundation.config`](foundation.config); edit it to tune the kernel.

## How it's built and updated

- `.github/workflows/kernel.yml` runs **every Monday**: if Ubuntu has published a new kernel source (they do
  so for every security fix), it builds a new Foundation kernel and publishes it as a `kernel-<version>`
  GitHub release. It also runs whenever `kernel/` changes, or on demand from the Actions tab.
- The ISO workflow then rebuilds the ISO with the newest Foundation kernel.
- On an installed system the Foundation kernel boots by default (its version, `6.8.12-…`, sorts above
  Ubuntu's `6.8.0-…`). Ubuntu's generic kernel stays installed as a fallback under **Advanced options**
  in the boot menu, and keeps receiving Ubuntu's security updates.

> **Updates on installed PCs:** new Foundation kernels reach installed systems once Foundation has a public
> package repository (planned). Until then, reinstall from a new ISO or install the release's
> `linux-image-*.deb` with `fpkg install`.

## Build it yourself

```bash
# Ubuntu 24.04, with deb-src enabled for noble, noble-updates and noble-security
sudo apt install build-essential bc bison flex libssl-dev libelf-dev dwarves rsync cpio kmod zstd dpkg-dev python3-pil
./build-kernel.sh                 # latest Ubuntu kernel source
./build-kernel.sh 6.8.0-149.149   # or a specific one
ls out/                           # linux-image-…-foundation_….deb, linux-headers-…
```

Takes about 1–2 hours on 4 cores. To put it in an ISO, copy `out/linux-image-*.deb` to `linux/kernel-debs/`
and run `sudo linux/build-iso.sh`.

## The research kernel

[`research/`](../research) is a separate, from-scratch kernel written in Rust - our long-term
experiment in a kernel designed entirely by Foundation. The Foundation kernel above is what ships, because
it runs real hardware and real software today.
