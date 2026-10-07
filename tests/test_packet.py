import pytest

from niimdesk.protocol import commands
from niimdesk.protocol.commands import HeartbeatType, InfoType
from niimdesk.protocol.packet import Packet, PacketError, PacketReader

from dumps import B1_V5_22, exchanges


def test_reference_frames_from_niimbluelib():
    assert commands.print_start_7b(1).to_bytes().hex(" ") == "55 55 01 07 00 01 00 00 00 00 00 07 aa aa"
    assert commands.set_page_size_6b(240, 384, 1).to_bytes().hex(" ") == "55 55 13 06 00 f0 01 80 00 01 65 aa aa"


def test_connect_has_prefix():
    assert commands.connect().to_bytes().hex(" ") == "03 55 55 c1 01 01 c1 aa aa"


def test_requests_match_real_b1_traffic():
    built = [
        commands.connect(),
        commands.printer_status_data(),
        commands.printer_info(InfoType.MODEL_ID),
        commands.printer_info(InfoType.SERIAL_NUMBER),
        commands.printer_info(InfoType.BATTERY),
        commands.heartbeat(HeartbeatType.PRINTER_INFO),
        commands.heartbeat(HeartbeatType.ADVANCED2),
        commands.rfid_info(),
    ]
    requests = [req for req, _ in exchanges(B1_V5_22)]
    assert [p.to_bytes() for p in built] == requests


def test_responses_parse_and_match_expected_ids():
    for req, resp in exchanges(B1_V5_22):
        request = Packet.from_bytes(req.removeprefix(b"\x03"))
        response = Packet.from_bytes(resp)
        assert response.command in commands.expected_responses(request)


def test_roundtrip():
    p = Packet(0x85, bytes(range(54)))
    assert Packet.from_bytes(p.to_bytes()) == p


def test_bad_checksum_rejected():
    with pytest.raises(PacketError):
        Packet.from_hex("5555c2010300aaaa")


def test_reader_reassembles_fragments_and_bundles():
    raw = bytes.fromhex("55554a01044faaaa5555f60101f6aaaa")
    reader = PacketReader()
    got = []
    for i in range(len(raw)):
        got += reader.feed(raw[i : i + 1])
    assert got == [Packet(0x4A, b"\x04"), Packet(0xF6, b"\x01")]


def test_reader_resyncs_after_garbage():
    reader = PacketReader()
    got = reader.feed(bytes.fromhex("00 13 55 55 c2 01 03 00 aa aa 55 55 c2 01 03 c0 aa aa"))
    assert got == [Packet(0xC2, b"\x03")]
    assert reader.feed(bytes.fromhex("55")) == []
    assert reader.feed(bytes.fromhex("55 4a 01 04 4f aa aa")) == [Packet(0x4A, b"\x04")]
