from PIL import Image, ImageDraw

from niimdesk.protocol import encoder
from niimdesk.protocol.commands import Req


def white(w, h):
    return Image.new("1", (w, h), 1)


def test_bit_order_black_is_one_msb_first():
    img = white(16, 1)
    img.putpixel((0, 0), 0)
    img.putpixel((9, 0), 0)
    cols, rows = encoder.image_rows(img)
    assert cols == 16
    assert rows == [bytes((0x80, 0x40))]


def test_width_padded_to_multiple_of_8_with_white():
    img = Image.new("1", (10, 1), 0)  # all black
    cols, rows = encoder.image_rows(img)
    assert cols == 16
    assert rows == [bytes((0xFF, 0xC0))]


def test_empty_rows_merge():
    enc = encoder.encode(white(384, 50))
    assert enc.rows == 50 and enc.cols == 384
    assert [(r.row, r.repeat, r.data) for r in enc.runs] == [(0, 50, None)]
    packets = encoder.image_packets(enc, 384)
    assert [p.to_bytes().hex(" ") for p in packets] == ["55 55 84 03 00 00 32 b5 aa aa"]


def test_runs_split_every_200_rows():
    enc = encoder.encode(white(384, 450))
    assert [(r.row, r.repeat) for r in enc.runs] == [(0, 200), (200, 200), (400, 50)]


def test_identical_pixel_rows_merge_and_change_breaks_run():
    img = white(384, 10)
    d = ImageDraw.Draw(img)
    d.line([(0, 2), (383, 2)], fill=0)
    d.line([(0, 3), (383, 3)], fill=0)
    d.line([(0, 4), (100, 4)], fill=0)
    enc = encoder.encode(img)
    assert [(r.row, r.repeat, r.black_pixels) for r in enc.runs] == [
        (0, 2, 0), (2, 2, 384), (4, 1, 101), (5, 5, 0),
    ]


def test_full_row_packet_uses_split_counts():
    img = white(384, 1)
    ImageDraw.Draw(img).line([(0, 0), (383, 0)], fill=0)
    (packet,) = encoder.image_packets(encoder.encode(img), 384)
    assert packet.command == Req.PRINT_BITMAP_ROW
    assert len(packet.data) == 54
    # row 0, counts 128/128/128 per third, repeat 1, 48 bytes of 0xff
    assert packet.data[:6] == bytes((0, 0, 128, 128, 128, 1))
    assert packet.data[6:] == b"\xff" * 48
    assert len(packet.to_bytes()) == 61


def test_indexed_row_matches_niimbluelib_example():
    # From niimbluelib: 5555 83 0e 007e 000400 01 0027 0028 0029 002a fa aaaa (96 px printhead)
    img = white(96, 127)
    for x in range(39, 43):
        img.putpixel((x, 126), 0)
    packets = encoder.image_packets(encoder.encode(img), 96)
    assert packets[-1].to_bytes().hex() == "5555830e007e00040001002700280029002afaaaaa"


def test_seven_pixels_use_bitmap_packet():
    img = white(384, 1)
    for x in range(7):
        img.putpixel((x, 0), 0)
    (packet,) = encoder.image_packets(encoder.encode(img), 384)
    assert packet.command == Req.PRINT_BITMAP_ROW


def test_total_count_mode_for_rows_wider_than_printhead():
    data = b"\xff" * 50
    assert encoder.pixel_counts(data, 384) == bytes((0, 400 & 0xFF, 400 >> 8))


def test_grayscale_input_is_thresholded():
    img = Image.new("L", (8, 1), 255)
    img.putpixel((0, 0), 10)
    img.putpixel((1, 0), 200)
    _, rows = encoder.image_rows(img)
    assert rows == [bytes((0x80,))]
