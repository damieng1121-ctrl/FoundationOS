#!/usr/bin/env bash
# Build the Stoa research kernel, its user programs, and bootable disk images in ./target.
set -euo pipefail
cd "$(dirname "$0")"
(cd user && cargo build --release)          # ring-3 programs (embedded into the kernel as /bin)
(cd kernel && cargo build --release)
(cd builder && cargo run --release --quiet -- ../kernel/target/x86_64-unknown-none/release/stoa-kernel ../target)
