#!/usr/bin/env bash
# Build the Stoa kernel and wrap it into bootable disk images in ./target.
set -euo pipefail
cd "$(dirname "$0")"
(cd kernel && cargo build --release)
(cd builder && cargo run --release --quiet -- ../kernel/target/x86_64-unknown-none/release/stoa-kernel ../target)
