"""Command line interface: scan, info, print, testpage, render."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from niimdesk import __version__
from niimdesk.config import Config, config_path
from niimdesk.models import DEFAULT_MODEL
from niimdesk.protocol.client import NiimbotClient, PrinterError
from niimdesk.protocol.commands import LabelType
from niimdesk.render.label import Label, image_label, print_image, testpage_label
from niimdesk.transport.base import TransportError
from niimdesk.transport.ble import BleTransport, scan

LABEL_TYPES = {"gaps": LabelType.WITH_GAPS, "black": LabelType.BLACK_MARK, "transparent": LabelType.TRANSPARENT}


def parse_size(text: str) -> tuple[float, float]:
    try:
        w, h = (float(v.replace(",", ".")) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("Größe als BREITExHÖHE in mm angeben, z. B. 50x30") from None
    if not (5 <= w <= 100 and 5 <= h <= 500):
        raise argparse.ArgumentTypeError("Größe außerhalb des sinnvollen Bereichs")
    return w, h


async def _find_transport(address: str | None, timeout: float) -> BleTransport:
    if address:
        return BleTransport(address)
    print(f"Suche Drucker ({timeout:g} s) …", file=sys.stderr)
    printers = await scan(timeout)  # B1 sorted first
    if not printers:
        raise TransportError("Kein NIIMBOT-Drucker gefunden. Ist er eingeschaltet und in der Nähe?")
    found = printers[0]
    print(f"Verwende {found.name} ({found.address})", file=sys.stderr)
    return BleTransport(found.device)


def _remember(transport: BleTransport) -> None:
    """Store the printer as last used one (the GUI connects to it on start)."""
    config = Config.load()
    if config.printer_address != transport.address:
        config.printer_address = transport.address
        config.printer_name = transport.name
        config.save()


async def cmd_scan(args: argparse.Namespace) -> int:
    printers = await scan(args.timeout)
    if not printers:
        print("Keine Drucker gefunden.")
        return 1
    for p in printers:
        rssi = f"{p.rssi} dBm" if p.rssi is not None else "?"
        print(f"{p.address}  {p.name:<20} {rssi}")
    return 0


async def cmd_info(args: argparse.Namespace) -> int:
    transport = await _find_transport(args.address, args.timeout)
    client = NiimbotClient(transport)
    info = await client.connect()
    _remember(transport)
    try:
        hb = await client.heartbeat()
        rfid = await client.rfid_info()
    finally:
        await client.disconnect()

    print(f"Modell:        {info.model_name} (ID {info.model_id})")
    print(f"Seriennummer:  {info.serial or '?'}")
    print(f"Firmware:      {info.software_version or '?'}  Hardware: {info.hardware_version or '?'}")
    print(f"Protokoll:     v{info.protocol_version}  Druckkopf: {info.printhead_width or '?'} px")
    print(f"Akku:          {hb.battery_percent if hb.battery_percent is not None else '?'} %")
    print(f"Deckel:        {_yes_no(hb.lid_closed, 'geschlossen', 'OFFEN')}")
    print(f"Papier:        {_yes_no(hb.paper_inserted, 'eingelegt', 'FEHLT')}")
    if rfid.tag_present:
        left = rfid.total_labels - rfid.used_labels
        print(f"Etiketten:     {rfid.barcode}, {rfid.used_labels}/{rfid.total_labels} benutzt ({left} übrig)")
    else:
        print("Etiketten:     kein RFID-Chip erkannt (keine Original-Rolle?)")
    return 0


def _yes_no(value: bool | None, yes: str, no: str) -> str:
    return "?" if value is None else (yes if value else no)


def _load_label(args: argparse.Namespace) -> Label:
    path = Path(args.file)
    if path.suffix.lower() == ".json":
        label = Label.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if args.size:
            label.width_mm, label.height_mm = args.size
        return label
    width, height = args.size or (50.0, 30.0)
    return image_label(str(path), width, height, dither=not args.no_dither)


def _offsets(args: argparse.Namespace) -> tuple[float, float]:
    config = Config.load()
    x = config.offset_x_mm if args.offset_x is None else args.offset_x
    y = config.offset_y_mm if args.offset_y is None else args.offset_y
    return x, y


async def _print_label(args: argparse.Namespace, label: Label) -> int:
    image = print_image(label, DEFAULT_MODEL.dpi, DEFAULT_MODEL.printhead_pixels, *_offsets(args))
    if args.preview:
        image.save(args.preview)
        print(f"Vorschau gespeichert: {args.preview}", file=sys.stderr)

    transport = await _find_transport(args.address, args.timeout)
    client = NiimbotClient(transport)
    info = await client.connect()
    _remember(transport)
    print(f"Verbunden: {info.model_name}, Firmware {info.software_version}", file=sys.stderr)

    def progress(stage: str, fraction: float) -> None:
        text = "Übertragung" if stage == "transfer" else "Druck"
        print(f"\r{text}: {fraction * 100:5.1f} %", end="", file=sys.stderr, flush=True)

    try:
        density = args.density if args.density is not None else label.density
        label_type = LABEL_TYPES[args.label_type] if args.label_type else label.label_type
        await client.print_image(image, density=density, label_type=label_type, copies=args.copies, progress=progress)
    finally:
        print(file=sys.stderr)
        await client.disconnect()
    print("Fertig.", file=sys.stderr)
    return 0


async def cmd_print(args: argparse.Namespace) -> int:
    return await _print_label(args, _load_label(args))


async def cmd_testpage(args: argparse.Namespace) -> int:
    width, height = args.size or (50.0, 30.0)
    return await _print_label(args, testpage_label(width, height))


async def cmd_render(args: argparse.Namespace) -> int:
    label = _load_label(args) if args.file else testpage_label(*(args.size or (50.0, 30.0)))
    printhead = 10_000 if args.full else DEFAULT_MODEL.printhead_pixels
    image = print_image(label, DEFAULT_MODEL.dpi, printhead, *_offsets(args))
    image.save(args.output)
    print(f"{args.output}: {image.width} × {image.height} px")
    return 0


async def cmd_diagnose(args: argparse.Namespace) -> int:
    """Show versions and check that the Bluetooth backend is usable (also a smoke test for packaged builds)."""
    import platform
    from importlib.metadata import PackageNotFoundError, version

    from bleak.backends.client import get_platform_client_backend_type

    from niimdesk.render.fonts import font_families

    try:
        bleak_version = version("bleak")
    except PackageNotFoundError:
        bleak_version = "?"
    client_cls, backend = get_platform_client_backend_type()  # imports the platform backend (WinRT/BlueZ)
    print(f"niimdesk       {__version__}")
    print(f"Python         {platform.python_version()} ({platform.system()} {platform.release()})")
    print(f"bleak          {bleak_version}, Backend {backend.value} ({client_cls.__name__})")
    print(f"Schriften      {len(font_families())} Familien")
    print(f"Konfiguration  {config_path()}")
    if args.scan:
        printers = await scan(args.timeout)
        print(f"Bluetooth      OK, {len(printers)} Drucker gefunden")
    return 0


async def cmd_calibrate(args: argparse.Namespace) -> int:
    config = Config.load()
    if args.offset_x is not None:
        config.offset_x_mm = args.offset_x
    if args.offset_y is not None:
        config.offset_y_mm = args.offset_y
    if args.offset_x is not None or args.offset_y is not None:
        config.save()
        print(f"Gespeichert in {config_path()}")
    print(f"Druckversatz: X {config.offset_x_mm:+.2f} mm (rechts), Y {config.offset_y_mm:+.2f} mm (unten)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="niimdesk", description="NIIMBOT B1 per Bluetooth ansteuern")
    parser.add_argument("--version", action="version", version=f"niimdesk {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="mehr Ausgaben (-vv: Pakete)")
    sub = parser.add_subparsers(dest="command", required=True)

    def connection_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("-a", "--address", help="Bluetooth-Adresse des Druckers (sonst automatisch suchen)")
        p.add_argument("--timeout", type=float, default=5.0, help="Suchdauer in Sekunden")

    def print_args(p: argparse.ArgumentParser) -> None:
        connection_args(p)
        p.add_argument("-s", "--size", type=parse_size, help="Etikettengröße BREITExHÖHE in mm (Standard 50x30)")
        p.add_argument("-d", "--density", type=int, choices=range(1, 6), help="Druckdichte 1–5")
        p.add_argument("-t", "--label-type", choices=LABEL_TYPES, help="Etikettentyp")
        p.add_argument("-c", "--copies", type=int, default=1, help="Anzahl Kopien")
        p.add_argument("--preview", help="gerendertes Bild zusätzlich als PNG speichern")
        offset_args(p)

    def offset_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--offset-y", type=float, metavar="MM",
                       help="Druckversatz nach unten in mm (negativ = nach oben); Standard: gespeicherte Kalibrierung")
        p.add_argument("--offset-x", type=float, metavar="MM",
                       help="Druckversatz nach rechts in mm (negativ = nach links); Standard: gespeicherte Kalibrierung")

    p = sub.add_parser("scan", help="Drucker in der Nähe suchen")
    p.add_argument("--timeout", type=float, default=5.0)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("info", help="Druckerinfo und Status anzeigen")
    connection_args(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("print", help="Bild (PNG/JPG) oder Vorlage (.json) drucken")
    p.add_argument("file")
    p.add_argument("--no-dither", action="store_true", help="Bilder mit Schwellwert statt Rasterung umwandeln")
    print_args(p)
    p.set_defaults(func=cmd_print)

    p = sub.add_parser("testpage", help="Testetikett drucken")
    print_args(p)
    p.set_defaults(func=cmd_testpage)

    p = sub.add_parser("diagnose", help="Versionen und Bluetooth-Unterstützung prüfen")
    p.add_argument("--scan", action="store_true", help="zusätzlich kurz nach Druckern suchen")
    p.add_argument("--timeout", type=float, default=3.0)
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("calibrate", help="Druckversatz anzeigen oder dauerhaft speichern")
    offset_args(p)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("render", help="Etikett nur als PNG rendern (ohne Drucker)")
    p.add_argument("file", nargs="?", help="Bild oder Vorlage; ohne Angabe: Testetikett")
    p.add_argument("-o", "--output", default="etikett.png")
    p.add_argument("-s", "--size", type=parse_size)
    p.add_argument("--no-dither", action="store_true")
    p.add_argument("--full", action="store_true", help="nicht auf die Druckkopfbreite zuschneiden")
    offset_args(p)
    p.set_defaults(func=cmd_render)

    return parser


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # old Windows consoles cannot print every character
    args = build_parser().parse_args(argv)
    level = logging.WARNING if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    try:
        code = asyncio.run(args.func(args))
    except (PrinterError, TransportError, OSError, ValueError) as e:
        print(f"\nFehler: {e}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
