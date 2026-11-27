"""The setup's own icon (an original one: an arrow into a tray, on blue), as a Windows .ico.

    python make_setup_icon.py OUT.ico [PREVIEW.png]

Each size is drawn for itself (four times over, then made smaller): the small ones simpler, so that they stay clear.
The sizes up to 48 are kept as Windows' own bitmaps (with their transparency), 256 as a PNG, as Windows' tools do.
"""

import io
import struct
import sys

from PIL import Image, ImageDraw

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TOP, BOTTOM = (79, 124, 247), (36, 64, 196)


def draw(size: int) -> Image.Image:
    k = 4
    n = size * k
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    small = size <= 24
    # The ground: a rounded square, lighter at the top.
    pad = round(n * (0.04 if small else 0.06))
    radius = round(n * 0.22)
    ground = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    gd = ImageDraw.Draw(ground)
    for y in range(n):
        t = y / max(1, n - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,)
        gd.line([(0, y), (n, y)], fill=colour)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, n - pad - 1, n - pad - 1], radius=radius, fill=255)
    img.paste(ground, (0, 0), mask)
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    # The tray: an open box at the bottom.
    stroke = round(n * (0.11 if small else 0.085))
    left, right = round(n * 0.24), round(n * 0.76)
    top, bottom = round(n * 0.56), round(n * 0.76)
    d.rounded_rectangle([left, bottom - stroke, right, bottom], radius=stroke // 2, fill=white)
    d.rounded_rectangle([left, top, left + stroke, bottom], radius=stroke // 2, fill=white)
    d.rounded_rectangle([right - stroke, top, right, bottom], radius=stroke // 2, fill=white)
    # The arrow, down into it.
    cx = n // 2
    shaft = round(n * (0.13 if small else 0.10))
    head_w = round(n * (0.40 if small else 0.34))
    head_top = round(n * 0.40)
    tip = round(n * (0.64 if small else 0.62))
    d.rounded_rectangle([cx - shaft // 2, round(n * 0.18), cx + shaft // 2, head_top + shaft], radius=shaft // 3, fill=white)
    d.polygon([(cx - head_w // 2, head_top), (cx + head_w // 2, head_top), (cx, tip)], fill=white)
    return img.resize((size, size), Image.LANCZOS)


def dib(img: Image.Image) -> bytes:
    """An image as Windows' .ico keeps a bitmap: its header, the pixels bottom up (BGRA), and a mask."""
    w, h = img.size
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytearray()
    data = img.load()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = data[x, y]
            pixels += bytes((b, g, r, a))
    row = ((w + 31) // 32) * 4
    mask = bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(row)
        for x in range(w):
            if data[x, y][3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    return header + bytes(pixels) + bytes(mask)


def main(out: str, preview: str = "") -> None:
    images = []
    for size in SIZES:
        img = draw(size)
        if size >= 256:
            buf = io.BytesIO()
            img.save(buf, "PNG", optimize=True)
            images.append((size, buf.getvalue()))
        else:
            images.append((size, dib(img)))
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    with open(out, "wb") as f:
        f.write(head + entries + blobs)
    if preview:
        sheet = Image.new("RGBA", (sum(SIZES) + 10 * len(SIZES) + 10, 276), (240, 240, 240, 255))
        x = 10
        for size in SIZES:
            sheet.alpha_composite(draw(size), (x, 10 + (256 - size) // 2))
            x += size + 10
        sheet.save(preview)


if __name__ == "__main__":
    main(*sys.argv[1:])
