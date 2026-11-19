#!/usr/bin/env bash
# Build the Stoa kernel as .deb packages.
#
#   ./build-kernel.sh                          # latest source of $SRC_PKG (default: linux-hwe-7.0)
#   ./build-kernel.sh 7.0.0-43.43~24.04.1      # a specific Ubuntu source version
#   SRC_PKG=linux ./build-kernel.sh            # Ubuntu 24.04's original 6.8 kernel instead
#   CONFIG_ONLY=1 ./build-kernel.sh            # stop after writing the merged .config (quick check)
#
# Output: kernel/out/linux-image-<release>_*.deb and linux-headers-<release>_*.deb
# Requires (Ubuntu 24.04): build-essential bc bison flex libssl-dev libelf-dev dwarves rsync cpio kmod
#   zstd dpkg-dev debhelper python3-pil libdw-dev, plus deb-src entries for noble, noble-updates and noble-security.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$HERE/work}"
OUT="${OUT:-$HERE/out}"
JOBS="${JOBS:-$(nproc)}"
log() { printf '\033[1;35m==> %s\033[0m\n' "$*"; }

# Ubuntu's hardware-enablement (HWE) kernel for 24.04: the newest kernel Ubuntu maintains for it.
SRC_PKG="${SRC_PKG:-linux-hwe-7.0}"
UBUNTU_VERSION="${1:-$(apt-cache showsrc "$SRC_PKG" | sed -n 's/^Version: //p' | sort -V | tail -1)}"
[[ -n "$UBUNTU_VERSION" ]] || { echo "no source for $SRC_PKG - enable deb-src for noble-updates" >&2; exit 1; }
ABI="$(echo "$UBUNTU_VERSION" | sed -E 's/^[0-9.]+-([0-9]+)\..*/\1/')"
UPSTREAM="$(echo "$UBUNTU_VERSION" | cut -d- -f1)"
log "Stoa kernel from Ubuntu $SRC_PKG $UBUNTU_VERSION (ABI $ABI)"

mkdir -p "$WORK" "$OUT"
cd "$WORK"
if [[ ! -d "src-$UBUNTU_VERSION" ]]; then
  log "Fetching source"
  apt-get source --download-only "$SRC_PKG=$UBUNTU_VERSION"
  dpkg-source --no-check -x "${SRC_PKG}_${UBUNTU_VERSION#*:}.dsc" "src-$UBUNTU_VERSION"
fi
SRC="$WORK/src-$UBUNTU_VERSION"

log "Base configuration: Ubuntu generic $UPSTREAM-$ABI"
if [[ ! -f "config-$ABI-generic" ]]; then
  apt-get download "linux-modules-$UPSTREAM-$ABI-generic"
  dpkg-deb --fsys-tarfile "linux-modules-$UPSTREAM-$ABI-generic"_*.deb | tar -xO "./boot/config-$UPSTREAM-$ABI-generic" > "config-$ABI-generic"
fi

cd "$SRC"
# The kernel's own packaging writes debian/; remove Ubuntu's packaging so they don't collide.
rm -rf debian debian.master debian.* 2>/dev/null || true
cp "$WORK/config-$ABI-generic" .config
scripts/kconfig/merge_config.sh -m .config "$HERE/stoa.config" >/dev/null
make olddefconfig >/dev/null
for opt in PREEMPT HZ_1000 NTSYNC LRU_GEN_ENABLED DEFAULT_BBR; do
  grep -q "^CONFIG_$opt=y" .config || { echo "stoa.config: CONFIG_$opt didn't take effect" >&2; exit 1; }
done
if [[ -n "${CONFIG_ONLY:-}" ]]; then
  cp .config "$OUT/config-$UPSTREAM-$ABI-stoa"
  log "Config written to $OUT/config-$UPSTREAM-$ABI-stoa"
  exit 0
fi

log "Stoa boot logo"
python3 "$HERE/make-logo.py" "$HERE/../linux/overlay/usr/share/stoa/logo-round-512.png" \
  drivers/video/logo/logo_linux_clut224.ppm

RELEASE_SUFFIX="-$ABI-stoa"
log "Building $(make -s kernelversion)$RELEASE_SUFFIX with $JOBS jobs"
export KBUILD_BUILD_USER=stoa KBUILD_BUILD_HOST=stoa-os
make -j"$JOBS" LOCALVERSION="$RELEASE_SUFFIX" KDEB_PKGVERSION="$UPSTREAM-$ABI.1stoa" bindeb-pkg

mv -f "$SRC"/../linux-image-*stoa*.deb "$SRC"/../linux-headers-*stoa*.deb "$OUT"/
rm -f "$SRC"/../linux-libc-dev_*.deb "$SRC"/../*.buildinfo "$SRC"/../*.changes
(cd "$OUT" && ls -1 *.deb > MANIFEST && sha256sum *.deb > SHA256SUMS)
log "Done: $(ls "$OUT"/*.deb | xargs -n1 basename | tr '\n' ' ')"
