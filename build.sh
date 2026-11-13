#!/usr/bin/env bash
# Build the Foundation kernel and wrap it into bootable disk images in ./target.
set -euo pipefail
cd "$(dirname "$0")"
(cd kernel && cargo build --release)
(cd builder && cargo run --release --quiet -- ../kernel/target/x86_64-unknown-none/release/foundation-kernel ../target)
