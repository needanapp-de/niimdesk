from niimdesk.protocol import parsers
from niimdesk.protocol.commands import ConnectResult
from niimdesk.protocol.packet import Packet

from dumps import B1_V5_22, exchanges

RESP = {Packet.from_bytes(r).command: Packet.from_bytes(r) for _, r in exchanges(B1_V5_22)}


def test_connect_and_protocol_version():
    assert parsers.parse_connect(RESP[0xC2]) == ConnectResult.CONNECTED_V3
    assert parsers.parse_protocol_version(RESP[0xB5]) == 3


def test_printer_info():
    assert parsers.parse_model_id(RESP[0x48]) == 4096
    assert parsers.parse_serial(RESP[0x4B]) == "G327071185"
    assert parsers.parse_battery(RESP[0x4A]) == 100


def test_heartbeat_printer_info():
    info = parsers.parse_heartbeat_printer_info(RESP[0xDE])
    assert info.hardware_version == "5.10"
    assert info.software_version == "5.22"
    assert info.printhead_width == 384
    assert info.resolution_class == 2


def test_heartbeat_advanced2():
    hb = parsers.parse_heartbeat(RESP[0xD9])
    assert hb.battery_percent == 100
    assert hb.lid_closed is True
    assert hb.paper_inserted is True
    assert hb.paper_rfid_ok is True


def test_heartbeat_advanced1_b1_old_firmware():
    data = bytes(9) + bytes((0, 3, 0, 1))
    hb = parsers.parse_heartbeat(Packet(0xDD, data))
    assert hb == parsers.Heartbeat(battery_percent=75, lid_closed=True, paper_inserted=True, paper_rfid_ok=True)


def test_rfid_info():
    info = parsers.parse_rfid_info(RESP[0x1B])
    assert info.tag_present
    assert info.barcode == "10262260"
    assert info.serial == "PZ1G221322004205"
    assert (info.total_labels, info.used_labels, info.label_type) == (276, 153, 1)


def test_rfid_no_tag():
    assert parsers.parse_rfid_info(Packet(0x1B, b"\x00")).tag_present is False


def test_print_status_with_error():
    st = parsers.parse_print_status(Packet(0xB3, bytes((0, 1, 100, 50, 0, 0, 2, 0, 0, 0))))
    assert (st.page, st.print_progress, st.feed_progress, st.error) == (1, 100, 50, 2)
