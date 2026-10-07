"""Printer communication on a dedicated asyncio thread.

bleak needs its own event loop; on Windows it also must not run on Qt's STA
main thread. All results are delivered to the GUI through Qt signals.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine
from typing import Any

from bleak.backends.device import BLEDevice
from PIL import Image
from PySide6.QtCore import QObject, Signal

from niimdesk.protocol.client import NiimbotClient, PrintCancelled, PrinterError
from niimdesk.protocol.parsers import Heartbeat, ParseError
from niimdesk.transport.base import TransportError
from niimdesk.transport.ble import BleTransport, scan

log = logging.getLogger(__name__)

_EXPECTED_ERRORS = (PrinterError, TransportError, ParseError)


def _message(e: BaseException) -> str:
    if isinstance(e, _EXPECTED_ERRORS):
        return str(e)
    return f"Unerwarteter Fehler: {type(e).__name__}: {e}"


class PrinterWorker(QObject):
    scan_finished = Signal(list)  # list[FoundPrinter]
    scan_failed = Signal(str)
    connecting = Signal(str)
    connected = Signal(object)  # PrinterInfo
    connect_failed = Signal(str)
    disconnected = Signal()
    heartbeat = Signal(object)  # Heartbeat
    rfid = Signal(object)  # RfidInfo
    print_progress = Signal(str, float)
    print_finished = Signal()
    print_failed = Signal(str)
    printer_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="printer-worker", daemon=True)
        self._thread.start()
        self._client: NiimbotClient | None = None
        self._cancel: asyncio.Event | None = None
        self._last_heartbeat: Heartbeat | None = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Coroutine[Any, Any, Any]) -> concurrent.futures.Future[Any]:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(self._log_crash)
        return future

    @staticmethod
    def _log_crash(future: concurrent.futures.Future[Any]) -> None:
        if not future.cancelled() and future.exception():
            log.error("Worker task crashed", exc_info=future.exception())

    # --- API for the GUI thread --------------------------------------------

    def scan(self, timeout: float = 5.0) -> None:
        self._submit(self._scan(timeout))

    def connect_printer(self, target: str | BLEDevice) -> None:
        self._submit(self._connect(target))

    def disconnect_printer(self) -> None:
        self._submit(self._disconnect())

    def print_image(self, image: Image.Image, density: int, label_type: int, copies: int) -> None:
        self._submit(self._print(image.copy(), density, label_type, copies))

    def cancel_print(self) -> None:
        cancel = self._cancel
        if cancel is not None:
            self._loop.call_soon_threadsafe(cancel.set)

    def shutdown(self) -> None:
        try:
            self._submit(self._disconnect()).result(timeout=5)
        except (concurrent.futures.TimeoutError, RuntimeError):
            log.warning("Disconnect on shutdown timed out")
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)

    # --- coroutines on the worker loop -------------------------------------

    async def _scan(self, timeout: float) -> None:
        try:
            self.scan_finished.emit(await scan(timeout))
        except Exception as e:
            self.scan_failed.emit(_message(e))

    async def _connect(self, target: str | BLEDevice) -> None:
        await self._disconnect()
        transport = BleTransport(target)
        self.connecting.emit(transport.name)
        client = NiimbotClient(transport)
        client.on_disconnect = lambda: self._handle_disconnect(client)
        client.on_printer_error = lambda e: self.printer_error.emit(str(e))
        try:
            info = await client.connect()
        except Exception as e:
            self.connect_failed.emit(_message(e))
            return

        self._client = client
        self._last_heartbeat = None
        self.connected.emit(info)
        await self._poll_status(client)
        await self._fetch_rfid(client)
        client.start_heartbeat(self._handle_heartbeat)

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.disconnect()

    def _handle_disconnect(self, client: NiimbotClient) -> None:
        # ignore late callbacks of a client that was already replaced
        if self._client is client or self._client is None:
            self._client = None
            self.disconnected.emit()

    async def _poll_status(self, client: NiimbotClient) -> None:
        try:
            self._handle_heartbeat(await client.heartbeat())
        except _EXPECTED_ERRORS as e:
            log.warning("Status request failed: %s", e)

    def _handle_heartbeat(self, hb: Heartbeat) -> None:
        previous, self._last_heartbeat = self._last_heartbeat, hb
        self.heartbeat.emit(hb)
        changed = previous is not None and (
            previous.lid_closed != hb.lid_closed or previous.paper_rfid_ok != hb.paper_rfid_ok
        )
        if changed and self._client is not None:
            asyncio.ensure_future(self._fetch_rfid(self._client))

    async def _fetch_rfid(self, client: NiimbotClient) -> None:
        try:
            self.rfid.emit(await client.rfid_info())
        except _EXPECTED_ERRORS as e:
            log.warning("RFID request failed: %s", e)

    async def _print(self, image: Image.Image, density: int, label_type: int, copies: int) -> None:
        client = self._client
        if client is None or not client.is_connected:
            self.print_failed.emit("Kein Drucker verbunden")
            return

        self._cancel = asyncio.Event()
        try:
            await client.print_image(
                image,
                density=density,
                label_type=label_type,
                copies=copies,
                progress=lambda stage, fraction: self.print_progress.emit(stage, fraction),
                cancel=self._cancel,
            )
        except PrintCancelled as e:
            self.print_failed.emit(str(e))
        except Exception as e:
            log.exception("Print failed")
            self.print_failed.emit(_message(e))
        else:
            self.print_finished.emit()
        finally:
            self._cancel = None

        if client.is_connected:
            await self._poll_status(client)
            await self._fetch_rfid(client)
