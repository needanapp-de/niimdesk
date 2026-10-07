"""NIIMBOT packet framing.

Frame layout: ``55 55 | CMD | LEN | DATA[LEN] | XOR(CMD, LEN, DATA) | AA AA``.
The connect request is additionally prefixed with ``03``.

Ported from niimbluelib by MultiMote (MIT), see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from dataclasses import dataclass

HEAD = b"\x55\x55"
TAIL = b"\xaa\xaa"
CONNECT_COMMAND = 0xC1
CONNECT_PREFIX = b"\x03"

# head + cmd + len + checksum + tail
FRAME_OVERHEAD = len(HEAD) + 1 + 1 + 1 + len(TAIL)


class PacketError(ValueError):
    """Raised for malformed frames."""


@dataclass(frozen=True)
class Packet:
    command: int
    data: bytes = b""

    def __post_init__(self) -> None:
        if not 0 <= self.command <= 0xFF:
            raise PacketError(f"Invalid command 0x{self.command:x}")
        if len(self.data) > 0xFF:
            raise PacketError(f"Payload too large ({len(self.data)} > 255 bytes)")

    @property
    def checksum(self) -> int:
        checksum = self.command ^ len(self.data)
        for b in self.data:
            checksum ^= b
        return checksum

    def to_bytes(self) -> bytes:
        frame = HEAD + bytes((self.command, len(self.data))) + self.data + bytes((self.checksum,)) + TAIL
        if self.command == CONNECT_COMMAND:
            return CONNECT_PREFIX + frame
        return frame

    @classmethod
    def from_bytes(cls, frame: bytes) -> Packet:
        if len(frame) < FRAME_OVERHEAD:
            raise PacketError(f"Packet is too small ({len(frame)} < {FRAME_OVERHEAD})")
        if frame[:2] != HEAD:
            raise PacketError("Invalid packet head")
        if frame[-2:] != TAIL:
            raise PacketError("Invalid packet tail")

        size = frame[3]
        if len(frame) != FRAME_OVERHEAD + size:
            raise PacketError(f"Invalid packet size ({len(frame)} != {FRAME_OVERHEAD + size})")

        packet = cls(frame[2], bytes(frame[4 : 4 + size]))
        if packet.checksum != frame[4 + size]:
            raise PacketError(f"Invalid packet checksum ({packet.checksum} != {frame[4 + size]})")
        return packet

    @classmethod
    def from_hex(cls, text: str) -> Packet:
        return cls.from_bytes(bytes.fromhex(text))

    def __repr__(self) -> str:
        return f"Packet(0x{self.command:02x}, {self.data.hex(' ') or '-'})"


class PacketReader:
    """Reassembles packets from arbitrarily fragmented chunks (e.g. BLE notifications).

    Garbage before a frame head and frames with a broken checksum are skipped,
    so the stream re-synchronises on the next ``55 55``.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Packet]:
        self._buf += chunk
        packets: list[Packet] = []

        while True:
            start = self._buf.find(HEAD)
            if start == -1:
                # A single trailing 0x55 may be the first half of the next head.
                keep = 1 if self._buf.endswith(HEAD[:1]) else 0
                del self._buf[: len(self._buf) - keep]
                break
            if start > 0:
                del self._buf[:start]

            if len(self._buf) < 4:
                break
            frame_len = FRAME_OVERHEAD + self._buf[3]
            if len(self._buf) < frame_len:
                break

            try:
                packets.append(Packet.from_bytes(bytes(self._buf[:frame_len])))
            except PacketError:
                # Not a real frame start, skip this head and search again.
                del self._buf[:1]
                continue
            del self._buf[:frame_len]

        return packets

    def clear(self) -> None:
        self._buf.clear()
