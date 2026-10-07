"""Real B1 traffic (firmware 5.22) from niimbluelib's test dumps (MIT, MultiMote)."""

B1_V5_22 = """
>> 03 55 55 c1 01 01 c1 aa aa
<< 55 55 c2 01 03 c0 aa aa
>> 55 55 a5 01 01 a5 aa aa
<< 55 55 b5 10 30 30 03 20 00 c8 00 00 00 0f 01 02 04 01 98 00 df aa aa
>> 55 55 40 01 08 49 aa aa
<< 55 55 48 02 10 00 5a aa aa
>> 55 55 40 01 0b 4a aa aa
<< 55 55 4b 0a 47 33 32 37 30 37 31 31 38 35 3a aa aa
>> 55 55 40 01 0a 4b aa aa
<< 55 55 4a 01 04 4f aa aa
>> 55 55 dc 01 03 de aa aa
<< 55 55 de 0a 05 0a 05 16 01 80 02 02 01 00 48 aa aa
>> 55 55 dc 01 04 d9 aa aa
<< 55 55 d9 09 20 41 04 4d 00 00 01 00 00 f9 aa aa
>> 55 55 1a 01 01 1a aa aa
<< 55 55 1b 27 88 1d 7e 4f d9 97 00 00 08 31 30 32 36 32 32 36 30 10 50 5a 31 47 32 32 31 33 32 32 30 30 34 32 30 35 01 14 00 99 01 3d aa aa
"""


def exchanges(dump: str) -> list[tuple[bytes, bytes]]:
    """Return (request, response) byte pairs."""
    lines = [line.split(" ", 1) for line in dump.strip().splitlines()]
    pairs = []
    for (d1, req), (d2, resp) in zip(lines[::2], lines[1::2]):
        assert d1 == ">>" and d2 == "<<"
        pairs.append((bytes.fromhex(req), bytes.fromhex(resp)))
    return pairs
