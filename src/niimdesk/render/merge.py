"""Serial printing: ``{Spalte}`` placeholders in label elements, filled from the rows of a table.

Placeholders work in every text-like value: the text of a text element, barcode data and every
QR code field. Table cells for QR fields with a fixed set of values are normalized, e.g.
"WPA2" -> "WPA", "ja" -> "1", "07.10.2026 18:00" -> "2026-10-07T18:00".
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from niimdesk.render import qrdata
from niimdesk.render.label import BARCODE_TYPES, BarcodeElement, Element, Label, QrElement, TextElement

PLACEHOLDER = re.compile(r"\{([^{}\n]+)\}")
COPIES_COLUMN = "Anzahl"  # optional table column: how often a row is printed
MAX_COPIES = 999
DATE_HINT = "TT.MM.JJJJ HH:MM"

_TYPED_KINDS = ("choice", "check", "datetime")
_TRUE = {"1", "ja", "j", "x", "true", "wahr", "yes", "y", "on"}
_FALSE = {"", "0", "nein", "n", "false", "falsch", "no", "off", "-"}
_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%y %H:%M", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y",
)


def placeholders(text: str) -> list[str]:
    """Column names referenced in ``text``."""
    return [name.strip() for name in PLACEHOLDER.findall(text) if name.strip()]


def key(name: str) -> str:
    """Comparable form of a column name: case and repeated spaces don't matter."""
    return " ".join(name.split()).casefold()


def lookup(record: Mapping[str, str]) -> dict[str, str]:
    return {key(k): v for k, v in record.items()}


# --- where placeholders can appear ------------------------------------------

@dataclass
class Slot:
    """A text value of an element that may contain placeholders."""

    element: Element
    name: str  # attribute of the element, or key in QrElement.values
    field: qrdata.Field | None = None
    usage: str = ""
    in_values: bool = False

    def get(self) -> str:
        if self.in_values:
            assert isinstance(self.element, QrElement)
            return self.element.values.get(self.name, self.field.default if self.field else "")
        return getattr(self.element, self.name)

    def set(self, value: str) -> None:
        if self.in_values:
            assert isinstance(self.element, QrElement)
            self.element.values[self.name] = value
        else:
            setattr(self.element, self.name, value)

    @property
    def is_whole(self) -> bool:
        """The value is exactly one placeholder (needed for choice/yes-no/date fields)."""
        return PLACEHOLDER.fullmatch(self.get().strip()) is not None


def slots(element: Element) -> list[Slot]:
    if isinstance(element, TextElement):
        return [Slot(element, "text", usage="Text")]
    if isinstance(element, BarcodeElement):
        return [Slot(element, "data", usage=BARCODE_TYPES.get(element.symbology, "Barcode"))]
    if isinstance(element, QrElement):
        qr_type = qrdata.QR_TYPES.get(element.content_type)
        if qr_type is None:
            return []
        if element.content_type == "text":
            return [Slot(element, "data", qr_type.fields[0], "QR-Code (Text)")]
        return [
            Slot(element, f.key, f, f"QR-Code {qr_type.title}: {f.label}", in_values=True) for f in qr_type.fields
        ]
    return []


def has_placeholders(label: Label) -> bool:
    return any(PLACEHOLDER.search(s.get()) for e in label.elements for s in slots(e))


# --- columns -----------------------------------------------------------------

@dataclass
class Column:
    name: str
    kind: str = "line"  # line | choice | check | datetime
    choices: tuple[tuple[str, str], ...] = ()
    usages: list[str] = field(default_factory=list)

    def allowed(self) -> list[str]:
        if self.kind == "choice":
            return [text for text, _ in self.choices]
        if self.kind == "check":
            return ["ja", "nein"]
        return []

    @property
    def hint(self) -> str:
        lines = ["Verwendet in: " + ", ".join(self.usages)]
        if self.kind in ("choice", "check"):
            lines.append("Erlaubt: " + ", ".join(self.allowed()))
        elif self.kind == "datetime":
            lines.append(f"Datum und Uhrzeit: {DATE_HINT}")
        return "\n".join(lines)


def columns(label: Label) -> list[Column]:
    """All table columns the label uses, in order of appearance."""
    found: dict[str, Column] = {}
    for element in label.elements:
        for slot in slots(element):
            for name in placeholders(slot.get()):
                column = found.get(key(name))
                if column is None:
                    typed = slot.field is not None and slot.field.kind in _TYPED_KINDS and slot.is_whole
                    column = found[key(name)] = Column(
                        name,
                        slot.field.kind if typed and slot.field else "line",
                        slot.field.choices if typed and slot.field else (),
                    )
                if slot.usage not in column.usages:
                    column.usages.append(slot.usage)
    return list(found.values())


def column_names(label: Label) -> list[str]:
    return [c.name for c in columns(label)]


def unique_column(label: Label, base: str) -> str:
    """``base``, or ``base 2``, ``base 3`` … if the label already uses that column."""
    used = {key(n) for n in column_names(label)}
    name, n = base, 2
    while key(name) in used:
        name, n = f"{base} {n}", n + 1
    return name


def missing_columns(label: Label, headers: Sequence[str]) -> list[str]:
    available = {key(h) for h in headers}
    return [name for name in column_names(label) if key(name) not in available]


def prune_sample(label: Label) -> None:
    """Drop example values of columns that are no longer used."""
    used = {key(n) for n in column_names(label)}
    label.sample = {k: v for k, v in label.sample.items() if key(k) in used}


def example_values(label: Label) -> dict[str, str]:
    """Example row for a new table, keyed by :func:`key`."""
    values = lookup(label.sample)
    return {key(c.name): values.get(key(c.name), "") for c in columns(label)}


# --- cell values <-> field values ---------------------------------------------

def to_table_value(f: qrdata.Field | None, value: str) -> str:
    """A field value the way it is written into a table cell (choice text, ja/nein, German date)."""
    if f is None:
        return value
    if f.kind == "choice":
        return next((text for text, v in f.choices if v == value), value)
    if f.kind == "check":
        return "ja" if value == "1" else "nein"
    if f.kind == "datetime" and value:
        try:
            return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return value
    return value


def from_table_value(f: qrdata.Field, value: str) -> tuple[str, str | None]:
    """Field value for a table cell, tolerant to spelling; returns ``(value, error)``."""
    text = value.strip()
    folded = text.casefold()
    if f.kind == "choice":
        if not text and f.default:
            return f.default, None
        for label, v in f.choices:
            first_word = label.split()[0].strip(",;()") if label.split() else label
            if folded in {v.casefold(), label.casefold(), first_word.casefold()}:
                return v, None
        for _label, v in f.choices:  # e.g. "WPA2" -> "WPA"
            if folded.startswith(v.casefold()):
                return v, None
        allowed = ", ".join(label for label, _ in f.choices)
        return value, f"{f.label}: „{text}“ ist nicht erlaubt (möglich: {allowed})"
    if f.kind == "check":
        if folded in _TRUE:
            return "1", None
        if folded in _FALSE:
            return "0", None
        return value, f"{f.label}: „{text}“ bitte als ja oder nein angeben"
    if f.kind == "datetime":
        if not text:
            return "", None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).isoformat(timespec="minutes"), None
            except ValueError:
                continue
        return value, f"{f.label}: „{text}“ ist kein Datum ({DATE_HINT})"
    return value, None


# --- filling -------------------------------------------------------------------

def fill_text(text: str, values: Mapping[str, str], missing: list[str] | None = None) -> str:
    """Replace placeholders; ``values`` is keyed by :func:`key`. Unknown columns stay as they are."""

    def replace(m: re.Match[str]) -> str:
        name = m.group(1).strip()
        if key(name) in values:
            return values[key(name)]
        if missing is not None:
            missing.append(name)
        return m.group(0)

    return PLACEHOLDER.sub(replace, text)


def _fill(element: Element, values: Mapping[str, str], strict: bool) -> list[str]:
    errors: list[str] = []
    for slot in slots(element):
        value = slot.get()
        if not PLACEHOLDER.search(value):
            continue
        missing: list[str] = []
        filled = fill_text(value, values, missing)
        if missing:
            errors += [f"Spalte „{name}“ fehlt in der Tabelle" for name in missing]
            continue  # the preview keeps showing the placeholder
        if slot.field is not None and slot.field.kind in _TYPED_KINDS:
            filled, error = from_table_value(slot.field, filled)
            if error:
                errors.append(error)
        slot.set(filled)
    if not errors and (error := element.validate()):
        errors.append(f"{element.TITLE}: {error}")
    return errors if strict else []


def fill_element(element: Element, record: Mapping[str, str], strict: bool = False) -> tuple[Element, list[str]]:
    """Copy of ``element`` with the placeholders replaced by the record's values."""
    filled = copy.deepcopy(element)
    return filled, _fill(filled, lookup(record), strict)


def fill_label(label: Label, record: Mapping[str, str], strict: bool = True) -> tuple[Label, list[str]]:
    """Copy of ``label`` for one table row, plus the problems that prevent printing it."""
    values = lookup(record)
    out = copy.copy(label)
    out.elements = []
    errors: list[str] = []
    for element in label.elements:
        filled = copy.deepcopy(element)
        errors += _fill(filled, values, strict)
        out.elements.append(filled)
    return out, list(dict.fromkeys(errors))


def copies_of(record: Mapping[str, str], default: int) -> tuple[int, str | None]:
    """Copies for a row from the optional "Anzahl" column; 0 means skip the row."""
    raw = lookup(record).get(key(COPIES_COLUMN), "").strip()
    if not raw:
        return default, None
    try:
        number = float(raw.replace(",", "."))
    except ValueError:
        number = -1
    if number < 0 or not number.is_integer():
        return 0, f"{COPIES_COLUMN}: „{raw}“ ist keine ganze Zahl"
    if number > MAX_COPIES:
        return 0, f"{COPIES_COLUMN}: höchstens {MAX_COPIES}"
    return int(number), None


@dataclass
class MergedRow:
    index: int  # position in the table's rows
    line: int  # row number in the spreadsheet, for messages
    label: Label
    copies: int
    errors: list[str]
    is_example: bool = False  # unchanged example row of a table created by niimdesk

    @property
    def ok(self) -> bool:
        return not self.errors


def merge_rows(
    label: Label,
    rows: Sequence[Mapping[str, str]],
    lines: Sequence[int],
    default_copies: int = 1,
    example: Mapping[str, str] | None = None,
) -> list[MergedRow]:
    """One label per table row. ``example`` (keyed by :func:`key`) marks the untouched example row."""
    out = []
    for index, (record, line) in enumerate(zip(rows, lines, strict=True)):
        filled, errors = fill_label(label, record, strict=True)
        copies, error = copies_of(record, default_copies)
        if error:
            errors.append(error)
        values = lookup(record)
        is_example = bool(example) and any(example.values()) and all(
            values.get(k, "").strip() == v.strip() for k, v in example.items()
        )
        out.append(MergedRow(index, line, filled, copies, errors, is_example))
    return out
