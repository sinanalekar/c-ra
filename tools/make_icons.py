"""Generate the CYR@ app icon set (pure stdlib): a modern
squircle badge with a teal-emerald gradient and a bold open
ring + core mark (the agent glyph). Supersampled 4x for clean
anti-aliased edges at every size."""
import struct
import zlib


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t)
                 for i in range(3))


TEAL = (34, 197, 160)
EMERALD = (13, 148, 116)
DEEP = (7, 40, 36)
RING = (233, 253, 247)     # near-white mark
CORE = (52, 226, 178)     # bright core dot


def _squircle_inside(x, y, w, h):
    """Rounded-rect coverage (superellipse-ish corner radius).
    Returns True if the pixel is inside the badge."""
    r = w * 0.225
    if x < r:
        cx, cy = r, r
        if y < r:
            return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        if y > h - r:
            return (x - cx) ** 2 + \
                   (y - (h - r)) ** 2 <= r * r
    if x > w - r:
        if y < r:
            return (x - (w - r)) ** 2 + \
                   (y - r) ** 2 <= r * r
        if y > h - r:
            return (x - (w - r)) ** 2 + \
                   (y - (h - r)) ** 2 <= r * r
    return True


def pixel_fn(w, h):
    """Render at 4x supersampling for smooth edges (bezier
    tail precomputed once per image, not per pixel)."""
    ss = 4
    cx, cy = 0.44 * w, 0.46 * h
    R = 0.27 * w
    th = 0.075 * w
    core = 0.105 * w
    tail = _bezier(
        (cx + R * 0.97, cy + th * 0.4),
        (cx + R * 1.05, cy + R * 1.15),
        (cx - R * 0.1, cy + R * 1.05), 72)
    tail_th = th * 0.95

    def shade(fx, fy):
        x, y = fx * w, fy * h
        if not _squircle_inside(x, y, w, h):
            return (0, 0, 0, 0)      # transparent outside
        g = fx * 0.45 + fy * 0.55
        if g < 0.5:
            base = _lerp(TEAL, EMERALD, g * 2)
        else:
            base = _lerp(EMERALD, DEEP,
                         (g - 0.5) * 2)
        sheen = max(0.0, 1 - (fx + fy) * 1.2) * 22
        base = tuple(min(255,
                         int(c + sheen))
                     for c in base)
        dx = x - cx
        dy = y - cy
        d = (dx * dx + dy * dy) ** 0.5
        ang = _angle(dx, dy)
        in_gap = -0.38 < ang < 0.38
        if abs(d - R) < th and not in_gap:
            return (*RING, 255)
        if d < core:
            return (*CORE, 255)
        if d > R - th and d < R + R * 0.9 and not in_gap:
            pass
        for px, py in tail:
            ddx = x - px
            ddy = y - py
            if ddx * ddx + ddy * ddy < tail_th * tail_th:
                return (*RING, 255)
        return (*base, 255)

    def px(x, y):
        r = g = b = a = 0
        for sy in range(ss):
            for sx in range(ss):
                c = shade((x + (sx + 0.5) / ss) / w,
                          (y + (sy + 0.5) / ss) / h)
                r += c[0]; g += c[1]; b += c[2]; a += c[3]
        n = ss * ss
        return (r // n, g // n, b // n, a // n)
    return px


import math


def _angle(dx, dy):
    return math.atan2(dy, dx)


def _bezier(p0, p1, p2, n):
    return [(p0[0] + (p1[0] - p0[0]) * 2 * t * (1 - t) +
             (p2[0] - p0[0]) * t * t,
             p0[1] + (p1[1] - p0[1]) * 2 * t * (1 - t) +
             (p2[1] - p0[1]) * t * t)
            for t in (i / n for i in range(n + 1))]


def write_png(path: str, w: int, h: int, pixel) -> None:
    rows = b""
    for y in range(h):
        rows += b"\x00"
        for x in range(w):
            rows += bytes(pixel(x, y))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" +
            png_chunk(b"IHDR", ihdr) +
            png_chunk(b"IDAT", zlib.compress(rows, 9)) +
            png_chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(blob)


def png_blob(w, h):
    rows = b""
    px = pixel_fn(w, h)
    for y in range(h):
        rows += b"\x00"
        for x in range(w):
            rows += bytes(px(x, y))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" +
            png_chunk(b"IHDR", ihdr) +
            png_chunk(b"IDAT", zlib.compress(rows, 9)) +
            png_chunk(b"IEND", b""))


def write_ico(path: str, pngs: list) -> None:
    n = len(pngs)
    header = struct.pack("<HHH", 0, 1, n)
    entries = b""
    offset = 6 + 16 * n
    body = b""
    for (w, h, blob) in pngs:
        wh = 0 if w >= 256 else w
        hh = 0 if h >= 256 else h
        entries += struct.pack("<BBBBHHII", wh, hh, 0, 0,
                               1, 32, len(blob), offset)
        body += blob
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(header + entries + body)


if __name__ == "__main__":
    import os
    d = os.path.join(os.path.dirname(__file__),
                     "..", "src-tauri", "icons")
    os.makedirs(d, exist_ok=True)
    for name, w, h in (("icon.png", 512, 512),
                       ("32x32.png", 32, 32),
                       ("128x128.png", 128, 128),
                       ("128x128@2x.png", 256, 256)):
        write_png(os.path.join(d, name), w, h,
                  pixel_fn(w, h))
        print("wrote", name)
    write_ico(os.path.join(d, "icon.ico"), [
        (32, 32, png_blob(32, 32)),
        (128, 128, png_blob(128, 128)),
        (256, 256, png_blob(256, 256))])
    print("wrote icon.ico (gradient squircle mark)")
