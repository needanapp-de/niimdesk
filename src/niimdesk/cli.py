"""Command line interface: scan, info, print, testpage, render, table."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from PIL import Image

from niimdesk import __version__
from niimdesk.config import Config, config_path
from niimdesk.models import DEFAULT_MODEL
from niimdesk.protocol.client import NiimbotClient, PrinterError
from niimdesk.protocol.commands import LabelType
from niimdesk.render import merge
from niimdesk.render.label import Label, image_label, print_image, testpage_label
from niimdesk.table import TABLE_SUFFIXES, TableError, read_table, write_template
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


def parse_rows(text: str) -> set[int]:
    """Spreadsheet row numbers like "3-10,12"."""
    rows: set[int] = set()
    try:
        for part in text.replace(" ", "").split(","):
            first, _, last = part.partition("-")
            rows.update(range(int(first), int(last or first) + 1))
    except ValueError:
        raise argparse.ArgumentTypeError("Zeilen wie in der Tabelle angeben, z. B. 3-10,12") from None
    return rows


def _load_label(args: argparse.Namespace) -> Label:
    path = Path(args.file)
    if path.suffix.lower() in TABLE_SUFFIXES:  # table created by niimdesk: contains its label
        table = read_table(path)
        if table.template is None:
            raise ValueError(
                f"{path.name} enthält keine Etikettenvorlage. Aufruf: niimdesk print VORLAGE.json --data {path.name}"
            )
        args.data = args.data or str(path)
        return Label.from_dict(table.template)
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


def _jobs(args: argparse.Namespace, label: Label, printhead: int) -> list[tuple[Image.Image, int, int | None]]:
    """``(image, copies, table row)`` per label; one per table row with ``--data``."""
    offsets = _offsets(args)
    copies = getattr(args, "copies", 1)
    data = getattr(args, "data", None)
    if not data:
        if merge.has_placeholders(label):  # without a table: the example values, like the app's preview
            label = merge.fill_label(label, label.sample, strict=False)[0]
        return [(print_image(label, DEFAULT_MODEL.dpi, printhead, *offsets), copies, None)]

    table = read_table(Path(data))
    if missing := merge.missing_columns(label, table.columns):
        raise ValueError(f"In der Tabelle fehlen die Spalten: {', '.join(missing)}")
    example = merge.example_values(Label.from_dict(table.template)) if table.template else {}
    rows = merge.merge_rows(label, table.rows, table.lines, copies, example)
    if args.rows:
        rows = [r for r in rows if r.line in args.rows]
    selected = []
    for row in rows:
        if row.is_example:
            print(f"Zeile {row.line}: Beispielzeile, wird übersprungen", file=sys.stderr)
        elif row.errors:
            print(f"Zeile {row.line}: {'; '.join(row.errors)}", file=sys.stderr)
        elif row.copies > 0:
            selected.append(row)
    if any(r.errors and not r.is_example for r in rows) and not args.skip_errors:
        raise ValueError("Die Tabelle enthält Fehler. Korrigieren oder mit --skip-errors nur die fehlerfreien Zeilen drucken.")
    if not selected:
        raise ValueError("Keine Zeile zu drucken.")
    return [(print_image(r.label, DEFAULT_MODEL.dpi, printhead, *offsets), r.copies, r.line) for r in selected]


async def _print_label(args: argparse.Namespace, label: Label) -> int:
    jobs = _jobs(args, label, DEFAULT_MODEL.printhead_pixels)
    if args.preview:
        jobs[0][0].save(args.preview)
        print(f"Vorschau gespeichert: {args.preview}", file=sys.stderr)
    if len(jobs) > 1:
        total = sum(copies for _, copies, _ in jobs)
        print(f"{total} Etiketten aus {len(jobs)} Tabellenzeilen", file=sys.stderr)

    transport = await _find_transport(args.address, args.timeout)
    client = NiimbotClient(transport)
    info = await client.connect()
    _remember(transport)
    print(f"Verbunden: {info.model_name}, Firmware {info.software_version}", file=sys.stderr)

    prefix = ""

    def progress(stage: str, fraction: float) -> None:
        text = "Übertragung" if stage == "transfer" else "Druck"
        print(f"\r{prefix}{text}: {fraction * 100:5.1f} %   ", end="", file=sys.stderr, flush=True)

    try:
        density = args.density if args.density is not None else label.density
        label_type = LABEL_TYPES[args.label_type] if args.label_type else label.label_type
        for i, (image, copies, line) in enumerate(jobs, start=1):
            prefix = f"[{i}/{len(jobs)}] Zeile {line}: " if line is not None else ""
            await client.print_image(image, density=density, label_type=label_type, copies=copies, progress=progress)
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
    output = Path(args.output)
    for image, _copies, line in _jobs(args, label, printhead):
        path = output if line is None else output.with_name(f"{output.stem}-{line:03d}{output.suffix}")
        image.save(path)
        print(f"{path}: {image.width} × {image.height} px")
    return 0


async def cmd_table(args: argparse.Namespace) -> int:
    path = Path(args.file)
    label = Label.from_dict(json.loads(path.read_text(encoding="utf-8")))
    output = Path(args.output) if args.output else path.with_name(f"{path.stem}-tabelle.xlsx")
    write_template(output, label, path.name)
    print(f"{output}: Spalten {', '.join(merge.column_names(label))}")
    return 0


async def cmd_diagnose(args: argparse.Namespace) -> int:
    """Show versions and check that the Bluetooth backend is usable (also a smoke test for packaged builds)."""
    import platform
    from importlib.metadata import PackageNotFoundError, version

    from bleak.backends.client import get_platform_client_backend_type

    from niimdesk.render.fonts import font_families

    def _version(package: str) -> str:
        try:
            return version(package)
        except PackageNotFoundError:
            return "?"

    import openpyxl  # fails here if the packaged build lacks it

    bleak_version = _version("bleak")
    client_cls, backend = get_platform_client_backend_type()  # imports the platform backend (WinRT/BlueZ)
    print(f"niimdesk       {__version__}")
    print(f"Python         {platform.python_version()} ({platform.system()} {platform.release()})")
    print(f"bleak          {bleak_version}, Backend {backend.value} ({client_cls.__name__})")
    print(f"Schriften      {len(font_families())} Familien")
    print(f"Tabellen       openpyxl {openpyxl.__version__}")
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

    def data_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--data", metavar="TABELLE", help="Seriendruck: ein Etikett pro Zeile (.xlsx oder .csv)")
        p.add_argument("--rows", type=parse_rows, metavar="3-10,12", help="nur diese Tabellenzeilen")
        p.add_argument("--skip-errors", action="store_true", help="fehlerhafte Tabellenzeilen auslassen")

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

    p = sub.add_parser("print", help="Bild (PNG/JPG), Vorlage (.json) oder Tabelle aus niimdesk (.xlsx) drucken")
    p.add_argument("file")
    p.add_argument("--no-dither", action="store_true", help="Bilder mit Schwellwert statt Rasterung umwandeln")
    print_args(p)
    data_args(p)
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
    data_args(p)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("table", help="Excel-Tabelle mit den Spalten einer Vorlage für den Seriendruck erstellen")
    p.add_argument("file", help="Vorlage (.json) mit {Spalte}-Feldern")
    p.add_argument("-o", "--output", help="Zieldatei (.xlsx oder .csv), Standard: VORLAGE-tabelle.xlsx")
    p.set_defaults(func=cmd_table)

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
    except (PrinterError, TransportError, TableError, OSError, ValueError) as e:
        print(f"\nFehler: {e}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
