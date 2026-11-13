#!/usr/bin/env bash
# Build Foundation and boot it in QEMU (BIOS). Pass --uefi to boot via OVMF instead.
set -euo pipefail
cd "$(dirname "$0")"
./build.sh
if [[ "${1:-}" == "--uefi" ]]; then
  OVMF="${OVMF:-/usr/share/ovmf/OVMF.fd}"
  exec qemu-system-x86_64 -bios "$OVMF" -drive format=raw,file=target/foundation-uefi.img -m 512M -serial stdio
fi
exec qemu-system-x86_64 -drive format=raw,file=target/foundation-bios.img -m 512M -serial stdio
