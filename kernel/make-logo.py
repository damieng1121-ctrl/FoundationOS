#!/usr/bin/env python3
"""Render the Stoa emblem as the kernel's boot logo (80x80, at most 224 colours, plain PPM)."""
import sys

from PIL import Image

src, out = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA").resize((80, 80), Image.LANCZOS)
bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
im = Image.alpha_composite(bg, im).convert("RGB").quantize(colors=224).convert("RGB")
w, h = im.size
px = list(im.getdata())
with open(out, "w") as f:
    f.write(f"P3\n# Stoa\n{w} {h}\n255\n")
    for i in range(0, len(px), 4):
        f.write("  ".join(f"{r:3d} {g:3d} {b:3d}" for r, g, b in px[i:i + 4]) + "\n")
