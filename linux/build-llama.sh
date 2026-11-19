#!/usr/bin/env bash
# Build the Stoa AI Local engine (llama.cpp's server) into a directory, e.g. $ROOT/usr/lib/stoa/llama.
#
#   ./build-llama.sh DEST
#
# CPU code is built for every x86-64 generation (picked at run time, so it's fast on old and new PCs alike)
# plus a Vulkan backend for AMD, Intel and NVIDIA graphics. The result is cached by release tag.
# Needs: cmake g++ git glslc libvulkan-dev spirv-headers
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?usage: build-llama.sh DEST}"
TAG="${LLAMA_TAG:-b12542}"
CACHE="${LLAMA_CACHE:-$HERE/work/llama-$TAG}"
log() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }

BUILD="$CACHE/src/build"
if [[ ! -x "$CACHE/out/llama-server.bin" ]]; then
  if [[ ! -x "$BUILD/bin/llama-server" ]]; then
    log "Building llama.cpp $TAG (CPU variants + Vulkan)"
    rm -rf "$CACHE"
    mkdir -p "$CACHE"
    git clone -q --depth 1 --branch "$TAG" https://github.com/ggml-org/llama.cpp "$CACHE/src"
    cmake -S "$CACHE/src" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release \
      -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
      -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON >/dev/null
    # Only the server and the backends it loads at run time (not llama.cpp's other tools).
    mapfile -t targets < <(cmake --build "$BUILD" --target help | grep -oE 'ggml-(cpu-[a-z0-9]+|vulkan)$' | sort -u)
    cmake --build "$BUILD" -j"$(nproc)" --target llama-server "${targets[@]}" >/dev/null
  fi
  mkdir -p "$CACHE/out"
  cp "$BUILD/bin/llama-server" "$CACHE/out/llama-server.bin"
  # The server, its libraries and the ggml backends (CPU variants, Vulkan) - not the other tools' libraries.
  for f in "$BUILD"/bin/lib{ggml,llama,llama-common,llama-server-impl,mtmd}*.so*; do
    case "$(basename "$f")" in libllama-*-impl.so) [[ "$f" == *server-impl* ]] || continue ;; esac
    cp -P "$f" "$CACHE/out/"
  done
  cp "$CACHE/src/LICENSE" "$CACHE/out/LICENSE"
  echo "$TAG" > "$CACHE/out/VERSION"
fi

log "Installing the Stoa AI Local engine ($TAG) into $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -P "$CACHE/out/"* "$DEST/"
strip --strip-unneeded "$DEST/llama-server.bin" "$DEST"/*.so* 2>/dev/null || true
cat > "$DEST/llama-server" <<'SH'
#!/bin/sh
# Stoa AI Local engine: llama.cpp's server with its libraries and backends (CPU variants, Vulkan) beside it.
D="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$D${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$D/llama-server.bin" "$@"
SH
chmod 0755 "$DEST/llama-server" "$DEST/llama-server.bin"
du -sh "$DEST" | cut -f1 | xargs -I{} echo "engine size: {}"
