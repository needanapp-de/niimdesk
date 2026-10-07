"""Command IDs, enums and packet builders for the NIIMBOT protocol.

Only the subset needed for the B1 is implemented. Values and payload layouts are
taken from niimbluelib by MultiMote (MIT), see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from enum import IntEnum

from niimdesk.protocol.packet import Packet


class Req(IntEnum):
    """Requests (client -> printer)."""

    PRINT_START = 0x01
    PAGE_START = 0x03
    SET_PAGE_SIZE = 0x13
    RFID_INFO = 0x1A
    SET_DENSITY = 0x21
    SET_LABEL_TYPE = 0x23
    PRINTER_INFO = 0x40
    GET_PAPER_INFO = 0x59
    PRINT_BITMAP_ROW_INDEXED = 0x83
    PRINT_EMPTY_ROW = 0x84
    PRINT_BITMAP_ROW = 0x85
    PRINT_STATUS = 0xA3
    PRINTER_STATUS_DATA = 0xA5
    CONNECT = 0xC1
    CANCEL_PRINT = 0xDA
    HEARTBEAT = 0xDC
    PAGE_END = 0xE3
    PRINT_END = 0xF3


class Resp(IntEnum):
    """Responses and unsolicited messages (printer -> client)."""

    NOT_SUPPORTED = 0x00
    PRINT_START = 0x02
    PAGE_START = 0x04
    SET_PAGE_SIZE = 0x14
    RFID_INFO = 0x1B
    SET_DENSITY = 0x31
    SET_LABEL_TYPE = 0x33
    GET_PAPER_INFO = 0x69
    PRINT_STATUS = 0xB3
    PRINTER_STATUS_DATA = 0xB5
    CONNECT = 0xC2
    RESET_TIMEOUT = 0xC6
    CANCEL_PRINT = 0xD0
    PRINTER_CHECK_LINE = 0xD3
    HEARTBEAT_ADVANCED2 = 0xD9
    PRINT_ERROR = 0xDB
    HEARTBEAT_ADVANCED1 = 0xDD
    HEARTBEAT_BASIC = 0xDE
    HEARTBEAT_PRINTER_INFO = 0xDF
    PRINTER_PAGE_INDEX = 0xE0
    PAGE_END = 0xE4
    PRINT_END = 0xF4


class InfoType(IntEnum):
    """Sub-types of the PRINTER_INFO request. The response command is ``0x40 + type``."""

    DENSITY = 1
    LABEL_TYPE = 3
    AUTO_SHUTDOWN_TIME = 7
    MODEL_ID = 8
    SOFTWARE_VERSION = 9
    BATTERY = 10
    SERIAL_NUMBER = 11
    HARDWARE_VERSION = 12
    BLUETOOTH_ADDRESS = 13


class HeartbeatType(IntEnum):
    ADVANCED1 = 1
    BASIC = 2
    PRINTER_INFO = 3
    ADVANCED2 = 4


class ConnectResult(IntEnum):
    DISCONNECT = 0
    CONNECTED = 1
    CONNECTED_NEW = 2
    CONNECTED_V3 = 3
    FIRMWARE_ERRORS = 90


class LabelType(IntEnum):
    WITH_GAPS = 1
    BLACK_MARK = 2
    CONTINUOUS = 3
    PERFORATED = 4
    TRANSPARENT = 5


LABEL_TYPE_NAMES = {
    LabelType.WITH_GAPS: "Etiketten mit Lücke",
    LabelType.BLACK_MARK: "Schwarzmarke",
    LabelType.CONTINUOUS: "Endlospapier",
    LabelType.PERFORATED: "Perforiert",
    LabelType.TRANSPARENT: "Transparent",
}


class PageColor(IntEnum):
    SINGLE = 0
    DOUBLE = 1


ERROR_MESSAGES = {
    0x01: "Deckel ist offen",
    0x02: "Kein Papier eingelegt",
    0x03: "Akku zu schwach",
    0x04: "Akkufehler",
    0x05: "Druck am Gerät abgebrochen",
    0x06: "Datenfehler",
    0x07: "Drucker überhitzt",
    0x08: "Papierausgabe gestört",
    0x09: "Drucker ist beschäftigt",
    0x0A: "Kein Druckkopf erkannt",
    0x0B: "Temperatur zu niedrig",
    0x0C: "Druckkopf locker",
    0x10: "Falsches Papier",
    0x11: "Papiereinstellung fehlgeschlagen",
    0x12: "Druckmodus konnte nicht gesetzt werden",
    0x13: "Druckdichte konnte nicht gesetzt werden",
    0x16: "Kommunikationsfehler",
    0x17: "Verbindung getrennt",
    0x18: "Ungültige Etikettenparameter",
    0x1C: "Papierprüfung fehlgeschlagen",
    0x1E: "Druckdichte wird nicht unterstützt",
    0x32: "Ungültige Seite",
    0x34: "Zeitüberschreitung beim Datenempfang",
}


def error_message(code: int) -> str:
    return ERROR_MESSAGES.get(code, f"Unbekannter Druckerfehler (Code 0x{code:02x})")


# Expected response IDs per request. None marks one-way packets without response.
RESPONSES: dict[int, tuple[int, ...] | None] = {
    Req.PRINT_START: (Resp.PRINT_START,),
    Req.PAGE_START: (Resp.PAGE_START,),
    Req.SET_PAGE_SIZE: (Resp.SET_PAGE_SIZE,),
    Req.RFID_INFO: (Resp.RFID_INFO,),
    Req.SET_DENSITY: (Resp.SET_DENSITY,),
    Req.SET_LABEL_TYPE: (Resp.SET_LABEL_TYPE,),
    Req.GET_PAPER_INFO: (Resp.GET_PAPER_INFO,),
    Req.PRINT_BITMAP_ROW_INDEXED: None,
    Req.PRINT_EMPTY_ROW: None,
    Req.PRINT_BITMAP_ROW: None,
    Req.PRINT_STATUS: (Resp.PRINT_STATUS,),
    Req.PRINTER_STATUS_DATA: (Resp.PRINTER_STATUS_DATA,),
    Req.CONNECT: (Resp.CONNECT,),
    Req.CANCEL_PRINT: (Resp.CANCEL_PRINT,),
    Req.HEARTBEAT: (
        Resp.HEARTBEAT_BASIC,
        Resp.HEARTBEAT_PRINTER_INFO,
        Resp.HEARTBEAT_ADVANCED1,
        Resp.HEARTBEAT_ADVANCED2,
    ),
    Req.PAGE_END: (Resp.PAGE_END,),
    Req.PRINT_END: (Resp.PRINT_END,),
}


def expected_responses(packet: Packet) -> tuple[int, ...] | None:
    """Response IDs that answer ``packet``; None for one-way packets."""
    if packet.command == Req.PRINTER_INFO:
        return (0x40 + packet.data[0],)
    try:
        return RESPONSES[packet.command]
    except KeyError:
        raise ValueError(f"No response mapping for command 0x{packet.command:02x}") from None


def u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


# --- Packet builders -------------------------------------------------------

def connect() -> Packet:
    return Packet(Req.CONNECT, b"\x01")


def printer_status_data() -> Packet:
    return Packet(Req.PRINTER_STATUS_DATA, b"\x01")


def printer_info(info_type: InfoType) -> Packet:
    return Packet(Req.PRINTER_INFO, bytes((info_type,)))


def heartbeat(heartbeat_type: HeartbeatType) -> Packet:
    return Packet(Req.HEARTBEAT, bytes((heartbeat_type,)))


def rfid_info() -> Packet:
    return Packet(Req.RFID_INFO, b"\x01")


def set_density(value: int) -> Packet:
    return Packet(Req.SET_DENSITY, bytes((value,)))


def set_label_type(value: int) -> Packet:
    return Packet(Req.SET_LABEL_TYPE, bytes((value,)))


def print_start_7b(total_pages: int, page_color: PageColor = PageColor.SINGLE) -> Packet:
    """B1 variant: ``[totalPages u16, 0, 0, 0, 0, pageColor]``."""
    return Packet(Req.PRINT_START, u16(total_pages) + b"\x00\x00\x00\x00" + bytes((page_color,)))


def page_start() -> Packet:
    return Packet(Req.PAGE_START, b"\x01")


def set_page_size_6b(rows: int, cols: int, copies: int) -> Packet:
    """B1 variant: ``[rows u16, cols u16, copies u16]``.

    The 4-byte variant makes the B1 print a blank first label or many copies.
    """
    return Packet(Req.SET_PAGE_SIZE, u16(rows) + u16(cols) + u16(copies))


def page_end() -> Packet:
    return Packet(Req.PAGE_END, b"\x01")


def print_status() -> Packet:
    return Packet(Req.PRINT_STATUS, b"\x01")


def print_end() -> Packet:
    return Packet(Req.PRINT_END, b"\x01")


def print_empty_rows(row: int, repeat: int) -> Packet:
    return Packet(Req.PRINT_EMPTY_ROW, u16(row) + bytes((repeat,)))


def print_bitmap_row(row: int, repeat: int, counts: bytes, row_data: bytes) -> Packet:
    return Packet(Req.PRINT_BITMAP_ROW, u16(row) + counts + bytes((repeat,)) + row_data)


def print_bitmap_row_indexed(row: int, repeat: int, counts: bytes, indexes: bytes) -> Packet:
    return Packet(Req.PRINT_BITMAP_ROW_INDEXED, u16(row) + counts + bytes((repeat,)) + indexes)
