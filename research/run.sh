#!/usr/bin/env bash
# Build Stoa and boot it in QEMU (BIOS). Pass --uefi to boot via OVMF instead.
set -euo pipefail
cd "$(dirname "$0")"
./build.sh
# A blank data disk for StoaFS (files saved in Stoa persist here between boots).
[[ -f target/stoa-data.img ]] || truncate -s 64M target/stoa-data.img
DATA=(-drive format=raw,file=target/stoa-data.img,index=1,media=disk)
if [[ "${1:-}" == "--uefi" ]]; then
  OVMF="${OVMF:-/usr/share/ovmf/OVMF.fd}"
  exec qemu-system-x86_64 -bios "$OVMF" -drive format=raw,file=target/stoa-uefi.img "${DATA[@]}" -m 512M -serial stdio
fi
exec qemu-system-x86_64 -drive format=raw,file=target/stoa-bios.img,index=0 "${DATA[@]}" -m 512M -serial stdio
