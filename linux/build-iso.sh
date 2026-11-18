#!/usr/bin/env bash
# Build the Stoa live/installer ISO.
#
#   sudo ./build-iso.sh            # full build -> out/stoa-<version>-amd64.iso
#   sudo ./build-iso.sh rootfs     # only (re)create the base root filesystem
#   sudo ./build-iso.sh customize  # re-apply overlay/ and setup to the cached rootfs
#   sudo ./build-iso.sh iso        # only pack squashfs + ISO
#
# Requires (Ubuntu 24.04 host): mmdebstrap squashfs-tools xorriso grub-pc-bin
# grub-efi-amd64-bin mtools
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$HERE/work}"
OUT="${OUT:-$HERE/out}"
MIRROR="${MIRROR:-http://archive.ubuntu.com/ubuntu}"
SECURITY_MIRROR="${SECURITY_MIRROR:-http://security.ubuntu.com/ubuntu}"
SUITE=noble
VERSION="$(cat "$HERE/VERSION")"
ROOT="$WORK/rootfs"
ISO="$WORK/iso"
ISO_NAME="stoa-${VERSION}-amd64.iso"

log() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

mount_chroot() {
  for d in proc sys dev dev/pts run; do mkdir -p "$ROOT/$d"; done
  mountpoint -q "$ROOT/proc"    || mount -t proc proc "$ROOT/proc"
  mountpoint -q "$ROOT/sys"     || mount -t sysfs sys "$ROOT/sys"
  mountpoint -q "$ROOT/dev"     || mount --bind /dev "$ROOT/dev"
  mountpoint -q "$ROOT/dev/pts" || mount --bind /dev/pts "$ROOT/dev/pts"
  mountpoint -q "$ROOT/run"     || mount -t tmpfs tmpfs "$ROOT/run"
  # /etc/resolv.conf in the image points into /run (systemd-resolved); give the chroot working DNS.
  mkdir -p "$ROOT/run/systemd/resolve"
  cp -L /etc/resolv.conf "$ROOT/run/systemd/resolve/stub-resolv.conf"
}
umount_chroot() {
  for d in run dev/pts dev sys proc; do
    mountpoint -q "$ROOT/$d" && umount -l "$ROOT/$d" || true
  done
}
trap umount_chroot EXIT

stage_rootfs() {
  log "Creating base root filesystem (Ubuntu $SUITE)"
  umount_chroot
  rm -rf "$ROOT"
  mkdir -p "$WORK"
  local pkgs
  pkgs="$(grep -vE '^\s*(#|$)' "$HERE/packages.txt" | tr '\n' ',' | sed 's/,$//')"
  local comps="main restricted universe multiverse"
  mmdebstrap \
    --variant=minbase \
    --architectures=amd64,i386 \
    --components="main,restricted,universe,multiverse" \
    --aptopt='APT::Install-Recommends "false"' \
    --aptopt='Acquire::Retries "5"' \
    --include="$pkgs" \
    --customize-hook='chroot "$1" apt-get clean' \
    "$SUITE" "$ROOT" \
    "deb $MIRROR $SUITE $comps" \
    "deb $MIRROR $SUITE-updates $comps" \
    "deb $SECURITY_MIRROR $SUITE-security $comps"
  touch "$WORK/.rootfs-done"
}

build_shell_helper() {
  # stoa-toplevels (Rust): tells the taskbar which windows are open.
  local dir="$HERE/shell/toplevels" bin="$HERE/shell/toplevels/target/release/stoa-toplevels"
  if command -v cargo >/dev/null 2>&1; then
    log "Building stoa-toplevels"
    (cd "$dir" && cargo build --release)
  fi
  [[ -x "$bin" ]] || { echo "stoa-toplevels is not built: install Rust (https://rustup.rs) and re-run" >&2; exit 1; }
  install -D -m 0755 "$bin" "$ROOT/usr/lib/stoa/stoa-toplevels"
}

vendor_python() {
  # Stoa AI: the Anthropic Python SDK, private to Stoa (system Python packages untouched).
  # Downloaded on the build host as wheels for the image's Python (3.12, x86_64).
  log "Installing the Anthropic SDK for Stoa AI"
  rm -rf "$ROOT/usr/lib/stoa/vendor"
  python3 -m pip install --quiet --no-cache-dir --disable-pip-version-check \
    --target "$ROOT/usr/lib/stoa/vendor" --python-version 3.12 --implementation cp \
    --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --only-binary=:all: \
    "anthropic==2.8.0" "openai==3.55.0"
  find "$ROOT/usr/lib/stoa/vendor" -name "__pycache__" -prune -exec rm -rf {} +
}

stage_kernel() {
  # Stoa kernel packages (from kernel/build-kernel.sh or a "kernel-*" GitHub release).
  local dir="${KERNEL_DEBS:-$HERE/kernel-debs}"
  rm -rf "$ROOT/tmp/stoa-kernel"
  if ls "$dir"/linux-image-*stoa*.deb >/dev/null 2>&1; then
    log "Including the Stoa kernel: $(ls "$dir"/linux-image-*stoa*.deb | xargs -n1 basename)"
    mkdir -p "$ROOT/tmp/stoa-kernel"
    cp "$dir"/linux-image-*stoa*.deb "$ROOT/tmp/stoa-kernel/"
  else
    log "No Stoa kernel packages in $dir - using Ubuntu's stock kernel"
  fi
}

stage_customize() {
  log "Applying Stoa overlay"
  cp -a "$HERE/overlay/." "$ROOT/"
  find "$ROOT/usr/lib/stoa" -name "__pycache__" -prune -exec rm -rf {} +
  build_shell_helper
  vendor_python
  stage_kernel
  cp "$HERE/VERSION" "$ROOT/usr/share/stoa/VERSION"
  install -m 0755 "$HERE/setup-rootfs.sh" "$ROOT/tmp/setup-rootfs.sh"
  mount_chroot
  log "Configuring the system inside the chroot"
  chroot "$ROOT" env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8 \
    STOA_VERSION="$VERSION" /tmp/setup-rootfs.sh
  rm -f "$ROOT/tmp/setup-rootfs.sh"
  umount_chroot
}

stage_iso() {
  log "Packing ISO tree"
  umount_chroot
  rm -rf "$ISO"
  mkdir -p "$ISO/casper" "$ISO/boot/grub" "$ISO/.disk" "$OUT"
  local kver
  kver="$(ls "$ROOT/boot" | sed -n 's/^vmlinuz-//p' | sort -V | tail -1)"
  cp "$ROOT/boot/vmlinuz-$kver" "$ISO/casper/vmlinuz"
  cp "$ROOT/boot/initrd.img-$kver" "$ISO/casper/initrd"

  chroot "$ROOT" dpkg-query -W --showformat='${Package} ${Version}\n' > "$ISO/casper/filesystem.manifest"
  # Packages the installer removes from the installed system.
  printf '%s\n' casper calamares > "$ISO/casper/filesystem.manifest-remove"
  du -sx --block-size=1 "$ROOT" | cut -f1 > "$ISO/casper/filesystem.size"

  # SQUASH_COMP=xz gives the smallest image (used for releases); zstd (default) unpacks faster.
  local comp=(-comp zstd -Xcompression-level "${SQUASH_LEVEL:-15}")
  [[ "${SQUASH_COMP:-zstd}" == "xz" ]] && comp=(-comp xz -Xbcj x86 -b 1M)
  log "Compressing root filesystem (squashfs/${SQUASH_COMP:-zstd})"
  mksquashfs "$ROOT" "$ISO/casper/filesystem.squashfs" -noappend "${comp[@]}" \
    -e boot/efi -wildcards -e 'proc/*' -e 'sys/*' -e 'dev/*' -e 'run/*' -e 'tmp/*'

  echo "Stoa $VERSION \"Bedrock\" - amd64 ($(date -u +%Y%m%d))" > "$ISO/.disk/info"
  cp "$HERE/iso/grub.cfg" "$ISO/boot/grub/grub.cfg"
  sed -i "s/@VERSION@/$VERSION/g" "$ISO/boot/grub/grub.cfg"
  mkdir -p "$ISO/boot/grub/themes"
  cp -a "$HERE/iso/theme" "$ISO/boot/grub/themes/stoa" 2>/dev/null || true

  log "Creating hybrid BIOS/UEFI ISO"
  grub-mkrescue -o "$OUT/$ISO_NAME" "$ISO" -- -volid STOA_OS
  (cd "$OUT" && sha256sum "$ISO_NAME" > "$ISO_NAME.sha256")
  log "Done: $OUT/$ISO_NAME ($(du -h "$OUT/$ISO_NAME" | cut -f1))"
}

case "${1:-all}" in
  rootfs) stage_rootfs ;;
  customize) stage_customize ;;
  iso) stage_iso ;;
  all)
    [[ -f "$WORK/.rootfs-done" ]] || stage_rootfs
    stage_customize
    stage_iso
    ;;
  *) echo "unknown stage: $1" >&2; exit 2 ;;
esac
