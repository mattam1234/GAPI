#!/usr/bin/env python3
"""
Generate the GAPI browser-extension toolbar icons.

Renders icon16/32/48/128.png into ``browser-extension/icons/`` with no
third-party dependencies (pure stdlib: zlib + struct). The artwork is a green
game-controller silhouette on a rounded dark badge, matching the extension's
GitHub-dark palette.

Usage:
    python generate_icons.py
"""

import os
import struct
import zlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(BASE_DIR, "icons")
SIZES = (16, 32, 48, 128)
SS = 4  # supersampling factor for anti-aliasing

# Palette (extension theme)
BG = (13, 17, 23)        # #0d1117 rounded badge
PAD = (46, 160, 67)      # #2ea043 controller body
DETAIL = (13, 17, 23)    # cut-out controls read as the badge colour


def _inside_rounded_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    # corner circles
    for cx in (x0 + r, x1 - r):
        for cy in (y0 + r, y1 - r):
            in_corner_region = (
                (cx == x0 + r and x < x0 + r) or (cx == x1 - r and x > x1 - r)
            ) and (
                (cy == y0 + r and y < y0 + r) or (cy == y1 - r and y > y1 - r)
            )
            if in_corner_region and (x - cx) ** 2 + (y - cy) ** 2 > r * r:
                return False
    return True


def _circle(x, y, cx, cy, r):
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _render(size):
    """Return RGBA bytes for one icon at the given pixel size."""
    n = size * SS
    px = bytearray(n * n * 4)

    for row in range(n):
        v = (row + 0.5) / n  # normalised 0..1, y-down
        for col in range(n):
            u = (col + 0.5) / n
            color = None

            # 1. rounded dark badge fills the whole tile
            if _inside_rounded_rect(u, v, 0.0, 0.0, 1.0, 1.0, 0.22):
                color = BG

                # 2. controller silhouette (two grips + bridge)
                pad = (
                    _circle(u, v, 0.28, 0.58, 0.205)
                    or _circle(u, v, 0.72, 0.58, 0.205)
                    or (0.28 <= u <= 0.72 and 0.40 <= v <= 0.66)
                )
                if pad:
                    color = PAD

                    # 3. d-pad cut-out (plus) on the left
                    dpad = (
                        (0.305 <= u <= 0.375 and 0.455 <= v <= 0.625)
                        or (0.265 <= u <= 0.415 and 0.495 <= v <= 0.585)
                    )
                    # 3b. two button cut-outs on the right
                    buttons = _circle(u, v, 0.645, 0.505, 0.052) or _circle(
                        u, v, 0.705, 0.585, 0.052
                    )
                    if dpad or buttons:
                        color = DETAIL

            o = (row * n + col) * 4
            if color is None:
                px[o:o + 4] = b"\x00\x00\x00\x00"
            else:
                px[o] = color[0]
                px[o + 1] = color[1]
                px[o + 2] = color[2]
                px[o + 3] = 255

    return _downsample(px, n, size)


def _downsample(px, n, size):
    """Box-average the supersampled RGBA buffer down to size x size."""
    out = bytearray(size * size * 4)
    area = SS * SS
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            for dy in range(SS):
                base = ((y * SS + dy) * n + x * SS) * 4
                for dx in range(SS):
                    o = base + dx * 4
                    r += px[o]
                    g += px[o + 1]
                    b += px[o + 2]
                    a += px[o + 3]
            o = (y * size + x) * 4
            out[o] = r // area
            out[o + 1] = g // area
            out[o + 2] = b // area
            out[o + 3] = a // area
    return bytes(out)


def _write_png(path, size, rgba):
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type: none
        raw.extend(rgba[y * size * 4:(y + 1) * size * 4])
    idat = zlib.compress(bytes(raw), 9)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


def main():
    os.makedirs(ICONS_DIR, exist_ok=True)
    for size in SIZES:
        rgba = _render(size)
        path = os.path.join(ICONS_DIR, f"icon{size}.png")
        _write_png(path, size, rgba)
        print(f"wrote {path} ({size}x{size})")


if __name__ == "__main__":
    main()
