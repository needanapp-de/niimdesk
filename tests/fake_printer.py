"""In-memory transport that behaves like a B1 (firmware 5.22)."""

import asyncio

from niimdesk.protocol.packet import Packet, PacketReader
from niimdesk.transport.base import Transport

from dumps import B1_V5_22, exchanges

_DUMP = {req.removeprefix(b"\x03"): resp for req, resp in exchanges(B1_V5_22)}
_OK_RESPONSES = {0x21: 0x31, 0x23: 0x33, 0x01: 0x02, 0x03: 0x04, 0x13: 0x14, 0xE3: 0xE4, 0xF3: 0xF4}


class FakeB1(Transport):
    def __init__(self, fragment: int = 3) -> None:
        super().__init__()
        self.sent: list[Packet] = []
        self.connected = False
        self.fragment = fragment
        self.copies = 0
        self.page = 0
        self.status_error: int | None = None  # error code reported by PrintStatus
        self.async_error: int | None = None  # 0xDB error sent instead of a PageEnd answer
        self.silent = False
        self._reader = PacketReader()

    @property
    def name(self) -> str:
        return "B1-FAKE"

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        if self.connected:
            self.connected = False
            self._emit_disconnect()

    async def write(self, data: bytes) -> None:
        for packet in self._reader.feed(data.removeprefix(b"\x03")):
            self.sent.append(packet)
            response = self._respond(packet)
            if response is not None and not self.silent:
                raw = response.to_bytes()
                for i in range(0, len(raw), self.fragment):
                    asyncio.get_running_loop().call_soon(self._emit_data, raw[i : i + self.fragment])

    def _respond(self, p: Packet) -> Packet | None:
        raw = p.to_bytes().removeprefix(b"\x03")
        if raw in _DUMP:
            return Packet.from_bytes(_DUMP[raw])
        if p.command == 0x01:
            self.copies = int.from_bytes(p.data[:2], "big")
            self.page = 0
        if p.command == 0xE3 and self.async_error is not None:
            return Packet(0xDB, bytes((self.async_error,)))
        if p.command in _OK_RESPONSES:
            return Packet(_OK_RESPONSES[p.command], b"\x01")
        if p.command == 0xA3:
            if self.status_error is not None:
                return Packet(0xB3, bytes((0, self.page, 0, 0, 0, 0, self.status_error, 0, 0, 0)))
            self.page = min(self.page + 1, self.copies)
            return Packet(0xB3, self.page.to_bytes(2, "big") + bytes((100, 100)))
        return None  # bitmap rows are one-way
