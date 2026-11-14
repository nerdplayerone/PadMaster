"""Make the logo files from the source image.

    python tools/make_icons.py <source image>

Writes:
  assets/logo.png         512 px copy of the source (kept in the repo)
  padlab/logo_128.png     small logo for the report header (embedded as base64)
  assets/padlab.ico       Windows icon for the .exe (16, 32, 48, 256 px)

Uses pygame-ce only (no new dependency). ICO entries hold PNG data, which
Windows Vista and later can read.
"""

import io
import os
import struct
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def png_bytes(surf) -> bytes:
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "x.png")
    return buf.getvalue()


def scaled(src, size: int):
    return pygame.transform.smoothscale(src, (size, size))


def write_ico(path: str, src) -> None:
    sizes = [16, 32, 48, 256]
    images = [png_bytes(scaled(src, s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        dim = 0 if s == 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(header + entries + b"".join(images))


def main(source: str) -> None:
    pygame.init()
    src = pygame.image.load(source)
    w, h = src.get_size()
    side = min(w, h)
    src = src.subsurface(((w - side) // 2, (h - side) // 2, side, side)).copy()
    pygame.image.save(scaled(src, 512), os.path.join(ROOT, "assets", "logo.png"))
    pygame.image.save(scaled(src, 128), os.path.join(ROOT, "padlab", "logo_128.png"))
    write_ico(os.path.join(ROOT, "assets", "padlab.ico"), src)
    print("Logo files written.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "assets", "logo.png"))
