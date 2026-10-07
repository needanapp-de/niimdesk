import asyncio

import pytest
from PIL import Image, ImageDraw

from niimdesk.protocol import client as client_module
from niimdesk.protocol.client import NiimbotClient, PrintCancelled, PrinterTimeout, PrintError

from fake_printer import FakeB1


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    monkeypatch.setattr(client_module, "STATUS_POLL_INTERVAL", 0)


def make_client(**kwargs):
    transport = FakeB1(**kwargs)
    return NiimbotClient(transport, packet_interval=0), transport


def label_image():
    img = Image.new("1", (384, 240), 1)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 383, 239], outline=0)
    d.text((20, 100), "Hallo B1", fill=0)
    return img


def test_connect_reads_printer_info():
    async def run():
        c, _ = make_client()
        return await c.connect()

    info = asyncio.run(run())
    assert info.model_name == "B1"
    assert info.protocol_version == 3
    assert info.serial == "G327071185"
    assert info.software_version == "5.22"
    assert info.hardware_version == "5.10"
    assert info.printhead_width == 384
    assert info.battery_percent == 100


def test_print_sequence_for_two_copies():
    async def run():
        c, t = make_client()
        await c.connect()
        t.sent.clear()
        stages = []
        await c.print_image(label_image(), density=3, copies=2, progress=lambda s, f: stages.append((s, f)))
        return t.sent, stages

    sent, stages = asyncio.run(run())
    cmds = [p.command for p in sent]

    assert cmds[:5] == [0x21, 0x23, 0x01, 0x03, 0x13]
    assert sent[0].data == b"\x03"
    assert sent[1].data == b"\x01"
    assert sent[2].data.hex() == "00020000000000"  # PrintStart: 2 pages, single color
    assert sent[4].data.hex() == "00f0018000" + "02"  # 240 rows, 384 cols, 2 copies
    assert cmds[-1] == 0xF3
    page_end = cmds.index(0xE3)
    assert set(cmds[5:page_end]) <= {0x83, 0x84, 0x85}
    assert all(c == 0xA3 for c in cmds[page_end + 1 : -1])
    assert stages[-1] == ("print", 1.0)
    assert any(s == "transfer" for s, _ in stages)


def test_status_error_raises_and_still_ends_print():
    async def run():
        c, t = make_client()
        await c.connect()
        t.status_error = 0x01
        with pytest.raises(PrintError, match="Deckel ist offen"):
            await c.print_image(label_image())
        return t.sent

    assert asyncio.run(run())[-1].command == 0xF3


def test_async_error_packet_fails_pending_request():
    async def run():
        c, t = make_client()
        await c.connect()
        t.async_error = 0x02
        with pytest.raises(PrintError, match="Kein Papier"):
            await c.print_image(label_image())

    asyncio.run(run())


def test_cancel_before_transfer():
    async def run():
        c, t = make_client()
        await c.connect()
        cancel = asyncio.Event()
        cancel.set()
        with pytest.raises(PrintCancelled):
            await c.print_image(label_image(), cancel=cancel)
        return [p.command for p in t.sent]

    cmds = asyncio.run(run())
    assert 0x85 not in cmds and cmds[-1] == 0xF3


def test_image_wider_than_printhead_rejected():
    async def run():
        c, _ = make_client()
        await c.connect()
        await c.print_image(Image.new("1", (400, 100), 1))

    with pytest.raises(Exception, match="Druckkopf"):
        asyncio.run(run())


def test_timeout_when_printer_silent():
    async def run():
        c, t = make_client()
        t.silent = True
        await c.connect()

    with pytest.raises(PrinterTimeout):
        asyncio.run(run())
