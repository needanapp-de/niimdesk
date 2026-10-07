"""Bluetooth LE transport based on bleak (Linux: BlueZ, Windows: WinRT).

The printer exposes one characteristic that is used in both directions:
responses arrive as notifications, requests are written without response.
No pairing is needed. On Windows the printer must NOT be paired in the system
settings, that leads to connect/disconnect loops.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDeviceNotFoundError, BleakError

from niimdesk.transport.base import Transport, TransportError

log = logging.getLogger(__name__)

SERVICE_UUID = "e7810a71-73ae-499d-8c15-faa9aef0c3f2"
CHARACTERISTIC_UUID = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"
_BLUETOOTH_BASE_UUID_SUFFIX = "-0000-1000-8000-00805f9b34fb"
_DEFAULT_WRITE_SIZE = 20


@dataclass
class FoundPrinter:
    address: str
    name: str
    rssi: int | None
    device: BLEDevice

    @property
    def is_b1(self) -> bool:
        return is_b1_name(self.name)


def is_b1_name(name: str) -> bool:
    """B1 advertises as ``B1-<serial>`` (some firmware ``B1_<serial>``)."""
    return name.startswith(("B1-", "B1_"))


async def scan(timeout: float = 5.0) -> list[FoundPrinter]:
    """Find NIIMBOT printers nearby, B1 first, then by signal strength."""
    try:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except BleakError as e:
        raise TransportError(f"Bluetooth-Suche fehlgeschlagen: {e}") from e
    except OSError as e:
        raise TransportError(f"Bluetooth nicht verfügbar: {e}") from e

    printers = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        uuids = {u.lower() for u in adv.service_uuids}
        if SERVICE_UUID in uuids or is_b1_name(name):
            printers.append(FoundPrinter(device.address, name, adv.rssi, device))

    printers.sort(key=lambda p: (not p.is_b1, -(p.rssi if p.rssi is not None else -999)))
    return printers


class BleTransport(Transport):
    def __init__(self, target: str | BLEDevice, connect_timeout: float = 20.0) -> None:
        super().__init__()
        self._target = target
        self._connect_timeout = connect_timeout
        self._client: BleakClient | None = None
        self._char: BleakGATTCharacteristic | None = None

    @property
    def name(self) -> str:
        if isinstance(self._target, BLEDevice):
            return self._target.name or self._target.address
        return self._target

    @property
    def address(self) -> str:
        return self._target.address if isinstance(self._target, BLEDevice) else self._target

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected and self._char is not None

    async def connect(self) -> None:
        try:
            client = await self._open_client()
        except BleakDeviceNotFoundError as e:
            # A connection left over from a crashed session keeps the printer from advertising.
            if not await _drop_stale_bluez_connection(self.address):
                raise TransportError(
                    f"{self.name} nicht gefunden. Ist der Drucker eingeschaltet, in der Nähe "
                    "und nicht mit der Handy-App verbunden?"
                ) from e
            client = await self._open_client()

        self._client = client
        try:
            self._char = self._find_characteristic(client)
            await client.start_notify(self._char, self._handle_notify)
            await self._wait_for_mtu()
        except BaseException:
            await self.disconnect()
            raise

        log.info("Connected to %s, write size %d", self.name, self._write_size())

    async def _open_client(self) -> BleakClient:
        client = BleakClient(
            self._target,
            disconnected_callback=self._handle_disconnect,
            timeout=self._connect_timeout,
        )
        try:
            await client.connect()
        except BleakDeviceNotFoundError:
            raise
        except (BleakError, TimeoutError, OSError) as e:
            raise TransportError(
                f"Verbindung zu {self.name} fehlgeschlagen ({e or type(e).__name__}). "
                "Ist der Drucker eingeschaltet und in der Nähe?"
            ) from e
        return client

    async def disconnect(self) -> None:
        client, self._client, self._char = self._client, None, None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except (BleakError, OSError) as e:
                log.warning("Disconnect failed: %s", e)

    async def write(self, data: bytes) -> None:
        if not self.is_connected:
            raise TransportError("Drucker ist nicht verbunden")
        assert self._client is not None and self._char is not None

        size = self._write_size()
        try:
            for i in range(0, len(data), size):
                await self._client.write_gatt_char(self._char, data[i : i + size], response=False)
        except (BleakError, OSError) as e:
            raise TransportError(f"Senden an den Drucker fehlgeschlagen: {e}") from e

    def _write_size(self) -> int:
        if self._char is None:
            return _DEFAULT_WRITE_SIZE
        return max(self._char.max_write_without_response_size, _DEFAULT_WRITE_SIZE)

    async def _wait_for_mtu(self, timeout: float = 2.0) -> None:
        """The negotiated MTU is often reported a moment after connecting."""
        try:
            async with asyncio.timeout(timeout):
                while self._write_size() <= _DEFAULT_WRITE_SIZE:
                    await asyncio.sleep(0.1)
        except TimeoutError:
            log.info("MTU stays at default, packets will be split into %d byte chunks", _DEFAULT_WRITE_SIZE)

    @staticmethod
    def _find_characteristic(client: BleakClient) -> BleakGATTCharacteristic:
        char = client.services.get_characteristic(CHARACTERISTIC_UUID)
        if char is not None:
            return char

        # Fallback like niimbluelib: first notify + write-without-response
        # characteristic in a vendor (non-standard) service.
        for service in client.services:
            if service.uuid.lower().endswith(_BLUETOOTH_BASE_UUID_SUFFIX):
                continue
            for c in service.characteristics:
                if "notify" in c.properties and "write-without-response" in c.properties:
                    return c

        raise TransportError("Keine passende Bluetooth-Schnittstelle gefunden. Ist das ein NIIMBOT-Drucker?")

    def _handle_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self._emit_data(bytes(data))

    def _handle_disconnect(self, _client: BleakClient) -> None:
        log.info("Printer %s disconnected", self.name)
        self._char = None
        self._emit_disconnect()


async def _drop_stale_bluez_connection(address: str) -> bool:
    """Linux only: disconnect a BlueZ-level connection nobody uses anymore. True if one was dropped."""
    bluetoothctl = shutil.which("bluetoothctl")
    if not sys.platform.startswith("linux") or bluetoothctl is None:
        return False

    async def run(*args: str) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            bluetoothctl, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
        return out

    try:
        if b"Connected: yes" not in await run("info", address):
            return False
        log.warning("Dropping stale Bluetooth connection to %s", address)
        await run("disconnect", address)
    except (OSError, TimeoutError) as e:
        log.warning("bluetoothctl failed: %s", e)
        return False
    await asyncio.sleep(2)  # give the printer time to advertise again
    return True
