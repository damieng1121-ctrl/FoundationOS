#!/usr/bin/env python3
"""Generate Foundation OS branding assets (logo, icons, wallpaper) with Pillow."""
import os, sys
from PIL import Image, ImageDraw, ImageFilter

OUT = sys.argv[1] if len(sys.argv) > 1 else "overlay"
S = 4  # supersampling factor


def logo(draw, x, y, s, fill):
    """Pediment over three columns on a stepped base (same proportions as the kernel UI)."""
    ph = s * 0.22
    draw.polygon([(x, y + ph), (x + s / 2, y), (x + s, y + ph)], fill=fill)
    draw.rectangle([x, y + ph, x + s, y + ph + s * 0.06], fill=fill)
    col_w, col_top, col_h = s * 0.14, y + ph + s * 0.10, s * 0.48
    for i in range(3):
        cx = x + s * 0.12 + i * s * 0.31
        draw.rectangle([cx, col_top, cx + col_w, col_top + col_h], fill=fill)
    by = col_top + col_h + s * 0.03
    draw.rectangle([x + s * 0.04, by, x + s * 0.96, by + s * 0.06], fill=fill)
    draw.rectangle([x, by + s * 0.08, x + s, by + s * 0.14], fill=fill)


def logo_png(size, color=(255, 255, 255, 255)):
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    logo(ImageDraw.Draw(im), size * S * 0.08, size * S * 0.1, size * S * 0.84, color)
    return im.resize((size, size), Image.LANCZOS)


def app_icon(size):
    big = size * S
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Vertical gradient rounded square.
    grad = Image.new("RGBA", (big, big))
    gd = ImageDraw.Draw(grad)
    top, bot = (0x5B, 0x9A, 0xFF), (0x3A, 0x5F, 0xD8)
    for yy in range(big):
        t = yy / big
        gd.line([(0, yy), (big, yy)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
    mask = Image.new("L", (big, big), 0)
    pad = big * 0.06
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, big - pad, big - pad], radius=big * 0.22, fill=255)
    im.paste(grad, (0, 0), mask)
    logo(d, big * 0.24, big * 0.24, big * 0.52, (255, 255, 255, 255))
    return im.resize((size, size), Image.LANCZOS)


def wallpaper(w=1920, h=1080):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    stops = [(0.0, (0x0B, 0x1A, 0x3A)), (0.6, (0x23, 0x40, 0x7A)), (1.0, (0x5A, 0x3F, 0x8C))]
    for yy in range(h):
        t = yy / h
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                d.line([(0, yy), (w, yy)], fill=tuple(int(a + (b - a) * u) for a, b in zip(c0, c1)))
                break
    # Soft glow + watermark logo.
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([w * 0.25, h * 0.15, w * 0.85, h * 0.95], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    im = Image.composite(Image.new("RGB", (w, h), (0x6E, 0x8F, 0xFF)), im, glow)
    mark = Image.new("L", (w, h), 0)
    s = int(h * 0.26)
    logo(ImageDraw.Draw(mark), w * 0.55 - s / 2, h * 0.36 - s / 2, s, 34)
    im = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), im, mark)
    # Horizon line.
    hl = Image.new("L", (w, h), 0)
    ImageDraw.Draw(hl).rectangle([0, h * 0.6 - 2, w, h * 0.6 + 2], fill=18)
    im = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), im, hl)
    return im


share = os.path.join(OUT, "usr/share/foundation")
os.makedirs(share, exist_ok=True)
wallpaper().save(os.path.join(share, "wallpaper.jpg"), quality=92)
logo_png(256).save(os.path.join(share, "logo-white.png"))
logo_png(64).save(os.path.join(share, "logo-white-64.png"))
for sz in (16, 22, 24, 32, 48, 64, 128, 256):
    p = os.path.join(OUT, f"usr/share/icons/hicolor/{sz}x{sz}/apps")
    os.makedirs(p, exist_ok=True)
    app_icon(sz).save(os.path.join(p, "foundation.png"))
app_icon(256).save(os.path.join(share, "foundation-256.png"))
# Calamares branding images.
cb = os.path.join(OUT, "etc/calamares/branding/foundation")
os.makedirs(cb, exist_ok=True)
app_icon(128).save(os.path.join(cb, "logo.png"))
wallpaper(960, 540).save(os.path.join(cb, "welcome.png"))
print("assets written to", OUT)
