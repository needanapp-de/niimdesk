"""Editor for QR code content: type selection (Wi-Fi, contact, ...) with type-specific fields."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QDateTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from niimdesk.render import qrdata
from niimdesk.render.label import QrElement

MIN_MODULE_MM = 0.4  # smaller QR dots are hard to scan from a thermal label

LEVELS = [
    ("L – 7 % (kleinster Code)", "L"),
    ("M – 15 % (Standard)", "M"),
    ("Q – 25 %", "Q"),
    ("H – 30 % (robustester Code)", "H"),
]


def _combo(items: list[tuple[str, str]]) -> QComboBox:
    box = QComboBox()
    for text, data in items:
        box.addItem(text, data)
    return box


def _iso_now_plus(hours: int) -> str:
    start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return (start + timedelta(hours=hours)).isoformat(timespec="minutes")


class QrContentEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._element: QrElement | None = None
        self._loading = False
        self._setters: list[Callable[[], None]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top = QFormLayout()
        self._type = _combo([(t.title, t.key) for t in qrdata.QR_TYPES.values()])
        self._type.currentIndexChanged.connect(self._on_type)
        top.addRow("Inhalt", self._type)
        layout.addLayout(top)

        self._notes = QLabel()
        self._notes.setWordWrap(True)
        self._notes.setStyleSheet("color: gray;")
        layout.addWidget(self._notes)

        self._fields_host = QWidget()
        self._fields = QFormLayout(self._fields_host)
        self._fields.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._fields_host)

        bottom = QFormLayout()
        self._level = _combo(LEVELS)
        self._level.setToolTip("Wie viel vom Code beschädigt sein darf. Höher = robuster, aber größerer Code.")
        self._level.currentIndexChanged.connect(self._on_level)
        bottom.addRow("Fehlerkorrektur", self._level)
        layout.addLayout(bottom)

        self._info = QLabel()
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFixedHeight(64)
        self._preview.setToolTip("So steht der Inhalt im QR-Code")
        self._preview.setStyleSheet("font-family: monospace; font-size: 8pt;")
        layout.addWidget(QLabel("Kodierter Inhalt"))
        layout.addWidget(self._preview)

    # --- public ------------------------------------------------------------

    def set_element(self, element: QrElement | None) -> None:
        self._element = element
        if element is None:
            return
        self._loading = True
        try:
            index = self._type.findData(element.content_type)
            self._type.setCurrentIndex(max(index, 0))
            self._build_fields()
            self._sync_level()
        finally:
            self._loading = False
        self.refresh_info()

    def refresh_info(self) -> None:
        """Update the encoded preview and the readability hint (also after resizing)."""
        element = self._element
        if element is None:
            return
        if element.validate():
            self._preview.setPlainText("")
            self._info.setText("")
            return
        self._preview.setPlainText(element.payload())
        info = element.module_info()
        if info is None:
            self._info.setText("<span style='color:#d03030'>Zu viel Inhalt für einen QR-Code.</span>")
            return
        modules, size_mm = info
        text = f"Raster {modules} × {modules}, Punktgröße {size_mm:.2f} mm".replace(".", ",")
        if size_mm < MIN_MODULE_MM:
            text = (
                f"<span style='color:#c07000'>⚠ {text}: schwer lesbar. QR-Code größer machen, "
                "weniger Inhalt eingeben oder „MeCard“ statt vCard verwenden.</span>"
            )
        self._info.setText(text)

    # --- internals ---------------------------------------------------------

    def _qr_type(self) -> qrdata.QrType:
        return qrdata.QR_TYPES[self._type.currentData()]

    def _value(self, key: str) -> str:
        e = self._element
        assert e is not None
        return e.data if e.content_type == "text" else e.values.get(key, "")

    def _store(self, key: str, value: str) -> None:
        e = self._element
        if self._loading or e is None:
            return
        if e.content_type == "text":
            if e.data == value:
                return
            e.data = value
        else:
            if e.values.get(key) == value:
                return
            e.values[key] = value
        self.refresh_info()
        self.changed.emit()

    def _on_type(self, _index: int) -> None:
        e = self._element
        if self._loading or e is None:
            return
        qr_type = self._qr_type()
        e.content_type = qr_type.key
        for f in qr_type.fields:  # defaults so that e.g. the Wi-Fi security choice is preset
            if f.kind == "datetime" and not e.values.get(f.key):
                e.values[f.key] = _iso_now_plus(1 if f.key == "end" else 0)
            elif f.default and f.key not in e.values:
                e.values[f.key] = f.default
        self._loading = True
        try:
            self._build_fields()
            self._sync_level()
        finally:
            self._loading = False
        self.refresh_info()
        self.changed.emit()

    def _on_level(self, _index: int) -> None:
        e = self._element
        if self._loading or e is None or self._qr_type().error_correction:
            return
        e.error_correction = self._level.currentData()
        self.refresh_info()
        self.changed.emit()

    def _sync_level(self) -> None:
        e = self._element
        assert e is not None
        forced = self._qr_type().error_correction
        index = self._level.findData(forced or e.error_correction)
        self._level.setCurrentIndex(max(index, 0))
        self._level.setEnabled(forced is None)
        self._level.setToolTip(
            "Vom Format vorgeschrieben" if forced else "Wie viel vom Code beschädigt sein darf. Höher = robuster, aber größerer Code."
        )

    def _build_fields(self) -> None:
        while self._fields.rowCount():
            self._fields.removeRow(0)
        qr_type = self._qr_type()
        self._notes.setText(qr_type.notes)
        self._notes.setVisible(bool(qr_type.notes))
        for f in qr_type.fields:
            self._add_field(f)

    def _add_field(self, f: qrdata.Field) -> None:
        value = self._value(f.key) or f.default
        key = f.key

        if f.kind == "multiline":
            w = QPlainTextEdit()
            w.setFixedHeight(64)
            w.setPlaceholderText(f.placeholder)
            w.setPlainText(value)
            w.textChanged.connect(lambda: self._store(key, w.toPlainText()))
            self._fields.addRow(f.label, w)
        elif f.kind == "choice":
            w = _combo(list(f.choices))
            w.setCurrentIndex(max(w.findData(value), 0))
            w.currentIndexChanged.connect(lambda _: self._store(key, w.currentData()))
            self._fields.addRow(f.label, w)
        elif f.kind == "check":
            w = QCheckBox(f.label)
            w.setChecked(value == "1")
            w.toggled.connect(lambda checked: self._store(key, "1" if checked else "0"))
            self._fields.addRow(w)
        elif f.kind == "datetime":
            w = QDateTimeEdit()
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy HH:mm")
            parsed = QDateTime.fromString(value, "yyyy-MM-ddTHH:mm")
            w.setDateTime(parsed if parsed.isValid() else QDateTime.currentDateTime())
            w.dateTimeChanged.connect(lambda dt: self._store(key, dt.toString("yyyy-MM-ddTHH:mm")))
            self._fields.addRow(f.label, w)
        else:
            w = QLineEdit(value)
            w.setPlaceholderText(f.placeholder)
            w.textChanged.connect(lambda text: self._store(key, text))
            self._fields.addRow(f.label, w)
