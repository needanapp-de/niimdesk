"""Async NIIMBOT client: request/response handling, printer info, heartbeat and the B1 print task.

The print sequence ("B1" print task) follows niimbluelib by MultiMote (MIT):
SetDensity, SetLabelType, PrintStart(7 bytes), PageStart, SetPageSize(6 bytes),
bitmap rows, PageEnd, poll PrintStatus until all copies are done, PrintEnd.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from PIL import Image

from niimdesk.models import DEFAULT_MODEL, PrinterModel, model_by_id
from niimdesk.protocol import commands, encoder, parsers
from niimdesk.protocol.commands import ConnectResult, HeartbeatType, InfoType, Resp, error_message
from niimdesk.protocol.packet import Packet, PacketReader
from niimdesk.transport.base import Transport, TransportError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1.0
HEARTBEAT_TIMEOUT = 1.0
PAGE_TIMEOUT = 10.0
STATUS_TIMEOUT = 5.0
STATUS_POLL_INTERVAL = 0.3
NO_PROGRESS_TIMEOUT = 30.0
PACKET_INTERVAL = 0.010  # sending rows faster makes the B1 drop data on large images

T = TypeVar("T")


class PrinterError(Exception):
    """Printer problem with a user-facing (German) message."""


class PrinterTimeout(PrinterError):
    pass


class PrintError(PrinterError):
    def __init__(self, code: int) -> None:
        super().__init__(error_message(code))
        self.code = code


class PrintCancelled(PrinterError):
    def __init__(self) -> None:
        super().__init__("Druck abgebrochen")


@dataclass
class PrinterInfo:
    model_id: int
    model: PrinterModel | None
    protocol_version: int
    serial: str | None = None
    software_version: str | None = None
    hardware_version: str | None = None
    battery_percent: int | None = None
    printhead_width: int | None = None

    @property
    def model_name(self) -> str:
        return self.model.name if self.model else f"Unbekannt (ID {self.model_id})"


# stage is "transfer" (sending image data) or "print" (printer working), fraction 0..1
ProgressCallback = Callable[[str, float], None]


class NiimbotClient:
    def __init__(self, transport: Transport, packet_interval: float = PACKET_INTERVAL) -> None:
        self.transport = transport
        self.packet_interval = packet_interval
        self.info: PrinterInfo | None = None
        self.printing = False

        self.on_disconnect: Callable[[], None] | None = None
        self.on_printer_error: Callable[[PrintError], None] | None = None

        self._reader = PacketReader()
        self._lock = asyncio.Lock()
        self._waiter: tuple[tuple[int, ...], asyncio.Future[Packet]] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        transport.on_data = self._handle_data
        transport.on_disconnect = self._handle_disconnect

    @property
    def is_connected(self) -> bool:
        return self.transport.is_connected and self.info is not None

    @property
    def model(self) -> PrinterModel:
        if self.info and self.info.model:
            return self.info.model
        return DEFAULT_MODEL

    # --- connection --------------------------------------------------------

    async def connect(self) -> PrinterInfo:
        self._reader.clear()
        await self.transport.connect()
        try:
            self.info = await self._negotiate()
        except BaseException:
            await self.transport.disconnect()
            raise
        return self.info

    async def disconnect(self) -> None:
        self.stop_heartbeat()
        self.info = None
        await self.transport.disconnect()

    async def _negotiate(self) -> PrinterInfo:
        result = parsers.parse_connect(await self.request(commands.connect()))
        protocol_version = 0
        if result == ConnectResult.CONNECTED_NEW:
            protocol_version = 1
        elif result == ConnectResult.CONNECTED_V3:
            protocol_version = parsers.parse_protocol_version(await self.request(commands.printer_status_data()))
        elif result not in (ConnectResult.CONNECTED, ConnectResult.CONNECTED_NEW):
            log.warning("Unexpected connect result %r", result)

        model_id = parsers.parse_model_id(await self.request(commands.printer_info(InfoType.MODEL_ID)))
        info = PrinterInfo(model_id=model_id, model=model_by_id(model_id), protocol_version=protocol_version)

        info.serial = await self._optional(parsers.parse_serial, commands.printer_info(InfoType.SERIAL_NUMBER))
        info.battery_percent = await self._optional(parsers.parse_battery, commands.printer_info(InfoType.BATTERY))

        details = await self._optional(
            parsers.parse_heartbeat_printer_info, commands.heartbeat(HeartbeatType.PRINTER_INFO)
        )
        if details:
            info.software_version = details.software_version
            info.hardware_version = details.hardware_version
            info.printhead_width = details.printhead_width
        else:
            info.software_version = await self._optional(
                parsers.parse_version, commands.printer_info(InfoType.SOFTWARE_VERSION)
            )
            info.hardware_version = await self._optional(
                parsers.parse_version, commands.printer_info(InfoType.HARDWARE_VERSION)
            )

        log.info("Printer: %s", info)
        return info

    async def _optional(self, parse: Callable[[Packet], T], packet: Packet) -> T | None:
        try:
            return parse(await self.request(packet))
        except (PrinterError, parsers.ParseError) as e:
            log.warning("Optional request 0x%02x failed: %s", packet.command, e)
            return None

    # --- request / response ------------------------------------------------

    async def request(self, packet: Packet, timeout: float = DEFAULT_TIMEOUT) -> Packet:
        """Send ``packet`` and wait for its response. One-way packets return themselves."""
        expected = commands.expected_responses(packet)

        async with self._lock:
            if expected is None:
                await self._write(packet)
                return packet

            future: asyncio.Future[Packet] = asyncio.get_running_loop().create_future()
            self._waiter = (expected, future)
            try:
                await self._write(packet)
                return await asyncio.wait_for(future, timeout)
            except TimeoutError:
                raise PrinterTimeout(
                    f"Keine Antwort vom Drucker (Befehl 0x{packet.command:02x})"
                ) from None
            finally:
                self._waiter = None

    async def _request_retry(self, packet: Packet, tries: int, timeout: float) -> Packet:
        for attempt in range(tries):
            try:
                return await self.request(packet, timeout)
            except PrinterTimeout:
                if attempt == tries - 1:
                    raise
                log.warning("Retrying 0x%02x", packet.command)
        raise AssertionError("unreachable")

    async def _write(self, packet: Packet) -> None:
        if not self.transport.is_connected:
            raise PrinterError("Drucker ist nicht verbunden")
        await asyncio.sleep(self.packet_interval)
        log.debug(">> %r", packet)
        try:
            await self.transport.write(packet.to_bytes())
        except TransportError as e:
            raise PrinterError(str(e)) from e

    def _handle_data(self, chunk: bytes) -> None:
        for packet in self._reader.feed(chunk):
            log.debug("<< %r", packet)
            if self._waiter and not self._waiter[1].done():
                expected, future = self._waiter
                if packet.command in expected:
                    future.set_result(packet)
                    continue
                if packet.command == Resp.PRINT_ERROR and packet.data:
                    future.set_exception(PrintError(packet.data[0]))
                    continue
                if packet.command == Resp.NOT_SUPPORTED:
                    future.set_exception(PrinterError("Befehl wird vom Drucker nicht unterstützt"))
                    continue

            if packet.command == Resp.PRINT_ERROR and packet.data:
                error = PrintError(packet.data[0])
                log.warning("Printer error: %s", error)
                if self.on_printer_error:
                    self.on_printer_error(error)

    def _handle_disconnect(self) -> None:
        self.stop_heartbeat()
        self.info = None
        if self._waiter and not self._waiter[1].done():
            self._waiter[1].set_exception(PrinterError("Verbindung zum Drucker verloren"))
        if self.on_disconnect:
            self.on_disconnect()

    # --- status ------------------------------------------------------------

    async def heartbeat(self) -> parsers.Heartbeat:
        protocol = self.info.protocol_version if self.info else 0
        hb_type = HeartbeatType.ADVANCED2 if protocol >= 3 else HeartbeatType.ADVANCED1
        packet = await self.request(commands.heartbeat(hb_type), HEARTBEAT_TIMEOUT)
        hb = parsers.parse_heartbeat(packet)
        if self.info and hb.battery_percent is not None:
            self.info.battery_percent = hb.battery_percent
        return hb

    async def rfid_info(self) -> parsers.RfidInfo:
        return parsers.parse_rfid_info(await self.request(commands.rfid_info()))

    def start_heartbeat(
        self,
        on_heartbeat: Callable[[parsers.Heartbeat], None],
        interval: float = 2.0,
        max_fails: int = 5,
    ) -> None:
        self.stop_heartbeat()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(on_heartbeat, interval, max_fails))

    def stop_heartbeat(self) -> None:
        task, self._heartbeat_task = self._heartbeat_task, None
        if task and task is not asyncio.current_task():
            task.cancel()

    async def _heartbeat_loop(
        self, on_heartbeat: Callable[[parsers.Heartbeat], None], interval: float, max_fails: int
    ) -> None:
        fails = 0
        while True:
            await asyncio.sleep(interval)
            if self.printing:
                continue
            try:
                on_heartbeat(await self.heartbeat())
                fails = 0
            except (PrinterError, parsers.ParseError) as e:
                fails += 1
                log.warning("Heartbeat failed (%d/%d): %s", fails, max_fails, e)
                if fails >= max_fails:
                    log.error("Printer stopped answering, disconnecting")
                    self._heartbeat_task = None
                    await self.transport.disconnect()
                    return

    # --- printing ----------------------------------------------------------

    async def print_image(
        self,
        image: Image.Image,
        *,
        density: int | None = None,
        label_type: int = commands.LabelType.WITH_GAPS,
        copies: int = 1,
        progress: ProgressCallback | None = None,
        cancel: asyncio.Event | None = None,
    ) -> None:
        """Print ``image`` (width across the printhead, height = feed direction)."""
        if not self.is_connected:
            raise PrinterError("Drucker ist nicht verbunden")

        model = self.model
        if not model.supported:
            raise PrinterError(f"Der {model.name} wird von niimdesk noch nicht unterstützt")
        density = model.density_default if density is None else density
        if not model.density_min <= density <= model.density_max:
            raise PrinterError(f"Dichte muss zwischen {model.density_min} und {model.density_max} liegen")
        if not 1 <= copies <= 0xFFFF:
            raise PrinterError("Ungültige Anzahl Kopien")

        printhead = (self.info.printhead_width if self.info else None) or model.printhead_pixels
        encoded = encoder.encode(image)
        if encoded.cols > printhead:
            raise PrinterError(f"Bild ist {encoded.cols} px breit, der Druckkopf schafft nur {printhead} px")
        if encoded.rows == 0 or encoded.rows > 0xFFFF:
            raise PrinterError("Ungültige Bildhöhe")
        image_packets = encoder.image_packets(encoded, printhead)

        def report(stage: str, fraction: float) -> None:
            if progress:
                progress(stage, max(0.0, min(1.0, fraction)))

        def check_cancel() -> None:
            if cancel and cancel.is_set():
                raise PrintCancelled()

        self.printing = True
        try:
            await self._expect_ok(commands.set_density(density), "Druckdichte setzen")
            await self._expect_ok(commands.set_label_type(label_type), "Etikettentyp setzen")
            await self._expect_ok(commands.print_start_7b(copies), "Druckstart")
            check_cancel()

            await self._expect_ok(commands.page_start(), "Seitenstart", PAGE_TIMEOUT, strict=True)
            await self.request(commands.set_page_size_6b(encoded.rows, encoded.cols, copies), PAGE_TIMEOUT)

            for i, packet in enumerate(image_packets, 1):
                check_cancel()
                await self.request(packet)
                report("transfer", i / len(image_packets))

            await self._expect_ok(commands.page_end(), "Seitenende", PAGE_TIMEOUT, strict=True)
            await self._wait_until_printed(copies, report, check_cancel)
        finally:
            self.printing = False
            try:
                await self.request(commands.print_end())
            except PrinterError as e:
                log.warning("PrintEnd failed: %s", e)

    async def _expect_ok(self, packet: Packet, what: str, timeout: float = DEFAULT_TIMEOUT, strict: bool = False) -> None:
        response = await self.request(packet, timeout)
        if response.data[:1] != b"\x01":
            if strict:
                raise PrinterError(f"Drucker hat „{what}“ abgelehnt")
            log.warning("%s: unexpected response %r", what, response)

    async def _wait_until_printed(
        self, copies: int, report: Callable[[str, float], None], check_cancel: Callable[[], None]
    ) -> None:
        loop = asyncio.get_running_loop()
        last_state: tuple[int, int, int] | None = None
        last_change = loop.time()

        while True:
            check_cancel()
            await asyncio.sleep(STATUS_POLL_INTERVAL)
            status = parsers.parse_print_status(
                await self._request_retry(commands.print_status(), tries=2, timeout=STATUS_TIMEOUT)
            )
            if status.error:
                raise PrintError(status.error)

            report("print", (status.page + status.print_progress / 100) / copies if status.page < copies else 1.0)
            if status.page >= copies:
                return

            state = (status.page, status.print_progress, status.feed_progress)
            if state != last_state:
                last_state, last_change = state, loop.time()
            elif loop.time() - last_change > NO_PROGRESS_TIMEOUT:
                raise PrinterTimeout("Drucker meldet keinen Fortschritt mehr")
