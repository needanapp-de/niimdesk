"""Turn a black/white image into NIIMBOT bitmap row packets.

Each row is ``cols / 8`` bytes, most significant bit = leftmost pixel, 1 = black.
Consecutive identical rows are merged via the ``repeat`` field; runs are split
every 200 rows like the original implementation does (check-line boundary).

Ported from niimbluelib by MultiMote (MIT), see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from niimdesk.protocol import commands
from niimdesk.protocol.packet import Packet

CHECK_LINE_INTERVAL = 200
MAX_INDEXED_PIXELS = 6  # the printer powers off if an indexed row carries more
_INVERT = bytes(255 - i for i in range(256))


@dataclass
class RowRun:
    row: int
    repeat: int
    data: bytes | None  # None = empty (all white) rows
    black_pixels: int


@dataclass
class EncodedImage:
    rows: int
    cols: int
    runs: list[RowRun]


def to_monochrome(image: Image.Image, threshold: int = 128) -> Image.Image:
    """Convert to mode "1" with a hard threshold (no dithering)."""
    if image.mode == "1":
        return image
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image.convert("RGBA"))
    return image.convert("L").point(lambda v: 255 if v >= threshold else 0, mode="1")


def image_rows(image: Image.Image) -> tuple[int, list[bytes]]:
    """Return ``(cols, rows)`` with the width padded (white) to a multiple of 8."""
    image = to_monochrome(image)
    width, height = image.size
    cols = (width + 7) // 8 * 8
    if cols != width:
        padded = Image.new("1", (cols, height), 1)
        padded.paste(image, (0, 0))
        image = padded

    # Pillow packs mode "1" as 1 = white; the printer wants 1 = black.
    raw = image.tobytes().translate(_INVERT)
    stride = cols // 8
    return cols, [raw[y * stride : (y + 1) * stride] for y in range(height)]


def encode(image: Image.Image) -> EncodedImage:
    cols, rows = image_rows(image)
    runs: list[RowRun] = []

    for y, data in enumerate(rows):
        black = int.from_bytes(data, "big").bit_count()
        row_data = data if black else None

        if runs and y % CHECK_LINE_INTERVAL != 0 and runs[-1].data == row_data:
            runs[-1].repeat += 1
        else:
            runs.append(RowRun(y, 1, row_data, black))

    return EncodedImage(rows=len(rows), cols=cols, runs=runs)


def pixel_counts(data: bytes, printhead_pixels: int) -> bytes:
    """The three "black pixel count" bytes of a bitmap row packet.

    Split mode (rows that fit the printhead): count per third of the printhead.
    Total mode otherwise: ``[0, total_lo, total_hi]``.
    """
    chunk = printhead_pixels // 8 // 3
    if chunk and len(data) <= chunk * 3:
        parts = [0, 0, 0]
        for i, b in enumerate(data):
            parts[i // chunk] += b.bit_count()
        return bytes(min(p, 255) for p in parts)

    total = int.from_bytes(data, "big").bit_count()
    return bytes((0, total & 0xFF, (total >> 8) & 0xFF))


def pixel_indexes(data: bytes) -> bytes:
    """Absolute x positions of all black pixels, each as u16 big endian."""
    out = bytearray()
    for byte_pos, b in enumerate(data):
        for bit in range(8):
            if b & (0x80 >> bit):
                out += commands.u16(byte_pos * 8 + bit)
    return bytes(out)


def image_packets(encoded: EncodedImage, printhead_pixels: int) -> list[Packet]:
    packets: list[Packet] = []
    for run in encoded.runs:
        if run.data is None:
            packets.append(commands.print_empty_rows(run.row, run.repeat))
            continue

        counts = pixel_counts(run.data, printhead_pixels)
        if run.black_pixels <= MAX_INDEXED_PIXELS:
            packets.append(commands.print_bitmap_row_indexed(run.row, run.repeat, counts, pixel_indexes(run.data)))
        else:
            packets.append(commands.print_bitmap_row(run.row, run.repeat, counts, run.data))
    return packets
