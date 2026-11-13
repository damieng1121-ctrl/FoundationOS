#!/usr/bin/env bash
# Build the Foundation OS live/installer ISO.
#
#   sudo ./build-iso.sh            # full build -> out/foundation-<version>-amd64.iso
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
ISO_NAME="foundation-${VERSION}-amd64.iso"

log() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

mount_chroot() {
  for d in proc sys dev dev/pts run; do mkdir -p "$ROOT/$d"; done
  mountpoint -q "$ROOT/proc"    || mount -t proc proc "$ROOT/proc"
  mountpoint -q "$ROOT/sys"     || mount -t sysfs sys "$ROOT/sys"
  mountpoint -q "$ROOT/dev"     || mount --bind /dev "$ROOT/dev"
  mountpoint -q "$ROOT/dev/pts" || mount --bind /dev/pts "$ROOT/dev/pts"
  mountpoint -q "$ROOT/run"     || mount -t tmpfs tmpfs "$ROOT/run"
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

stage_customize() {
  log "Applying Foundation overlay"
  cp -a "$HERE/overlay/." "$ROOT/"
  cp "$HERE/VERSION" "$ROOT/usr/share/foundation/VERSION"
  install -m 0755 "$HERE/setup-rootfs.sh" "$ROOT/tmp/setup-rootfs.sh"
  mount_chroot
  log "Configuring the system inside the chroot"
  chroot "$ROOT" env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8 \
    FOUNDATION_VERSION="$VERSION" /tmp/setup-rootfs.sh
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

  log "Compressing root filesystem (squashfs/zstd)"
  mksquashfs "$ROOT" "$ISO/casper/filesystem.squashfs" -noappend -comp zstd -Xcompression-level "${SQUASH_LEVEL:-15}" \
    -e boot/efi -wildcards -e 'proc/*' -e 'sys/*' -e 'dev/*' -e 'run/*' -e 'tmp/*'

  echo "Foundation OS $VERSION \"Bedrock\" - amd64 ($(date -u +%Y%m%d))" > "$ISO/.disk/info"
  cp "$HERE/iso/grub.cfg" "$ISO/boot/grub/grub.cfg"
  sed -i "s/@VERSION@/$VERSION/g" "$ISO/boot/grub/grub.cfg"
  mkdir -p "$ISO/boot/grub/themes"
  cp -a "$HERE/iso/theme" "$ISO/boot/grub/themes/foundation" 2>/dev/null || true

  log "Creating hybrid BIOS/UEFI ISO"
  grub-mkrescue -o "$OUT/$ISO_NAME" "$ISO" -- -volid FOUNDATION_OS
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
