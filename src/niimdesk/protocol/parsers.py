"""Response parsers.

Layouts follow niimbluelib by MultiMote (MIT), see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from niimdesk.protocol.commands import ConnectResult, Resp
from niimdesk.protocol.packet import Packet


class ParseError(ValueError):
    pass


def _require(packet: Packet, min_len: int, exact: bool = False) -> None:
    n = len(packet.data)
    if (exact and n != min_len) or n < min_len:
        raise ParseError(f"Unexpected payload length {n} for 0x{packet.command:02x}")


def _battery_percent(value: int) -> int:
    # Older firmware reports 0..4 steps instead of percent.
    return value * 25 if value <= 4 else value


@dataclass
class PrintStatus:
    page: int
    print_progress: int
    feed_progress: int
    error: int = 0


@dataclass
class Heartbeat:
    battery_percent: int | None = None
    lid_closed: bool | None = None
    paper_inserted: bool | None = None
    paper_rfid_ok: bool | None = None


@dataclass
class HeartbeatPrinterInfo:
    hardware_version: str
    software_version: str
    printhead_width: int
    resolution_class: int  # 2 = 203 dpi, 3 = 300 dpi
    printhead_alignment: int
    supports_rfid: bool


@dataclass
class RfidInfo:
    tag_present: bool
    uuid: str = ""
    barcode: str = ""
    serial: str = ""
    total_labels: int = -1
    used_labels: int = -1
    label_type: int = 0


def parse_bool(packet: Packet) -> bool:
    _require(packet, 1, exact=True)
    return packet.data[0] == 1


def parse_connect(packet: Packet) -> ConnectResult | int:
    _require(packet, 1)
    try:
        return ConnectResult(packet.data[0])
    except ValueError:
        return packet.data[0]


def parse_protocol_version(packet: Packet) -> int:
    """PRINTER_STATUS_DATA response -> protocol version (0 if unknown)."""
    if len(packet.data) < 13:
        return 0
    n = packet.data[11] * 100 + packet.data[12]
    if 204 <= n < 300:
        return 3
    if 300 <= n < 302:
        return 4
    if n >= 302:
        return 5
    return 0


def parse_model_id(packet: Packet) -> int:
    _require(packet, 1)
    if len(packet.data) == 1:
        return packet.data[0] << 8
    _require(packet, 2, exact=True)
    return int.from_bytes(packet.data, "big")


def parse_version(packet: Packet) -> str:
    _require(packet, 2, exact=True)
    major, minor = packet.data
    return f"{major + minor / 100:.2f}"


def parse_serial(packet: Packet) -> str:
    _require(packet, 1)
    if len(packet.data) >= 8:
        return packet.data.decode("ascii", errors="replace")
    if len(packet.data) >= 4:
        return packet.data[:4].hex().upper()
    return ""


def parse_battery(packet: Packet) -> int:
    _require(packet, 1, exact=True)
    return _battery_percent(packet.data[0])


def parse_heartbeat_printer_info(packet: Packet) -> HeartbeatPrinterInfo:
    """Response to heartbeat type 3 (``de``): versions and printhead geometry."""
    _require(packet, 10, exact=True)
    d = packet.data
    return HeartbeatPrinterInfo(
        hardware_version=f"{d[0] + d[1] / 100:.2f}",
        software_version=f"{d[2] + d[3] / 100:.2f}",
        printhead_width=int.from_bytes(d[4:6], "big"),
        resolution_class=d[6],
        printhead_alignment=d[7],
        supports_rfid=bool(d[8]),
    )


def parse_heartbeat(packet: Packet) -> Heartbeat:
    d = packet.data
    if packet.command == Resp.HEARTBEAT_ADVANCED2:
        _require(packet, 9)
        return Heartbeat(
            battery_percent=_battery_percent(d[2]),
            lid_closed=d[4] == 0,
            paper_inserted=d[5] == 0,
            paper_rfid_ok=d[6] != 0,
        )

    if packet.command == Resp.HEARTBEAT_ADVANCED1:
        n = len(d)
        if n == 10:
            return Heartbeat(lid_closed=d[8] == 0, battery_percent=_battery_percent(d[9]))
        if n in (13, 19):
            o = 9 if n == 13 else 15
            return Heartbeat(
                lid_closed=d[o] == 0,
                battery_percent=_battery_percent(d[o + 1]),
                paper_inserted=d[o + 2] == 0,
                paper_rfid_ok=d[o + 3] != 0,
            )
        if n == 20:
            return Heartbeat(paper_inserted=d[18] == 0, paper_rfid_ok=d[19] != 0)
        raise ParseError(f"Invalid heartbeat length {n}")

    raise ParseError(f"Unsupported heartbeat response 0x{packet.command:02x}")


def parse_print_status(packet: Packet) -> PrintStatus:
    _require(packet, 4)
    d = packet.data
    error = d[6] if len(d) == 10 else 0
    return PrintStatus(
        page=int.from_bytes(d[0:2], "big"),
        print_progress=d[2],
        feed_progress=d[3],
        error=error,
    )


def parse_rfid_info(packet: Packet) -> RfidInfo:
    d = packet.data
    if len(d) <= 1:
        return RfidInfo(tag_present=False)

    pos = 0

    def take(n: int) -> bytes:
        nonlocal pos
        if pos + n > len(d):
            raise ParseError("RFID response truncated")
        chunk = d[pos : pos + n]
        pos += n
        return chunk

    uuid = take(8).hex()
    barcode = take(take(1)[0]).decode("ascii", errors="replace")
    serial = take(take(1)[0]).decode("ascii", errors="replace")
    total = int.from_bytes(take(2), "big")
    used = int.from_bytes(take(2), "big")
    label_type = take(1)[0]
    return RfidInfo(True, uuid, barcode, serial, total, used, label_type)
