"""Generate the CYR@ app icon set (pure stdlib PNG/ICO
writers). The mark: a green @ glyph (ring + dot + sweeping
tail) on a dark slate field - drawn analytically, original."""
import struct
import zlib


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


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


SLATE = (14, 18, 24)
GREEN = (108, 214, 138)
EDGE = (44, 52, 66)


def _bezier_samples(p0, p1, p2, n=80):
    return [(p0[0] + (p1[0] - p0[0]) * 2 * t * (1 - t) +
             (p2[0] - p0[0]) * t * t,
             p0[1] + (p1[1] - p0[1]) * 2 * t * (1 - t) +
             (p2[1] - p0[1]) * t * t)
            for t in (i / n for i in range(n + 1))]


def pixel_fn(w, h):
    s = min(w, h)
    cx = w * 0.5
    cy = h * 0.44
    r = s * 0.21          # ring radius
    th = s * 0.055        # stroke thickness
    dot = s * 0.045       # center dot radius
    # the @ tail: from the ring's right side, sweeping down-left
    tail = _bezier_samples(
        (cx + r * 0.95, cy),
        (cx + r * 1.7, cy + r * 0.9),
        (cx - r * 0.15, cy + r * 1.85))
    # subtle corner accent lines
    m = s * 0.09

    def px(x, y):
        # background: vertical slate gradient
        t = y / h
        base = tuple(int(SLATE[i] + (10 - SLATE[i]) * -0.2 * t)
                     for i in range(3))
        d_ring = abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - r)
        d_dot = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        d_tail = min((x - tx) ** 2 + (y - ty) ** 2
                     for tx, ty in tail) ** 0.5
        # top-left / bottom-right corner accents
        corner_tl = (x < m and y < m) and \
            (x + y < m * 1.4)
        corner_br = (x > w - m and y > h - m) and \
            ((w - x) + (h - y) < m * 1.4)
        if d_ring < th or d_dot < dot or d_tail < th:
            return (*GREEN, 255)
        if corner_tl or corner_br:
            return (*EDGE, 255)
        return (*base, 255)
    return px


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
    print("wrote icon.ico (CYR@ mark)")
