"""Generate the app icon set (pure stdlib: PNG writer + ICO
writer) for the Tauri bundle. The mark: a shield chevron on a
dark slate field with a green verification band."""
import struct
import zlib


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


def write_png(path: str, w: int, h: int,
              pixel) -> None:
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


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t)
                 for i in range(3))


SLATE = (16, 20, 26)
GREEN = (111, 208, 140)
EDGE = (42, 49, 64)


def shield(x, y, w, h):
    """A simple shield silhouette: rounded top, tapering
    bottom point."""
    cx = w / 2
    ny = (y - h * 0.14) / (h * 0.72)     # 0 top, 1 tip
    if ny < 0 or ny > 1:
        return False
    # half-width shrinks from 0.36w at top to a point at tip
    hw = (0.36 - 0.34 * ny ** 1.6) * w
    if abs(x - cx) > hw:
        return False
    # rounded top corners
    top_r = 0.10 * h
    if y < h * 0.14 + top_r:
        dx = abs(x - cx) - (0.36 * w - top_r)
        dy = (h * 0.14 + top_r) - y
        if dx > 0 and dx ** 2 + dy ** 2 > top_r ** 2:
            return False
    return True


def pixel_fn(w, h):
    def px(x, y):
        if shield(x, y, w, h):
            # verification band across the shield
            band_top = h * 0.44
            band_bot = h * 0.56
            if band_top <= y <= band_bot:
                c = GREEN
            else:
                t = y / h
                c = lerp((30, 37, 49), (22, 27, 36), t)
            return (*c, 255)
        # field
        t = y / h
        c = lerp(SLATE, (12, 15, 20), t)
        return (*c, 255)
    return px


def write_ico(path: str, pngs: list) -> None:
    """ICO container wrapping PNG images (Vista+ format)."""
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


def png_blob(w, h):
    import io
    buf = io.BytesIO()

    class Fake:
        def write(self, b):
            buf.write(b)
            return len(b)
    # reuse write_png into a buffer
    rows = b""
    px = pixel_fn(w, h)
    for y in range(h):
        rows += b"\x00"
        for x in range(w):
            rows += bytes(px(x, y))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" +
            png_chunk(b"IHDR", ihdr) +
            png_chunk(b"IDAT", zlib.compress(rows, 9)) +
            png_chunk(b"IEND", b""))
    return blob


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
    blobs = [(32, 32, png_blob(32, 32)),
             (128, 128, png_blob(128, 128)),
             (256, 256, png_blob(256, 256))]
    write_ico(os.path.join(d, "icon.ico"), blobs)
    print("wrote icon.ico")
