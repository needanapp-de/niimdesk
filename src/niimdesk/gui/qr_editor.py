"""Editor for QR code content: type selection (Wi-Fi, contact, ...) with type-specific fields.

Every field can take its value from a table column instead (serial printing): the field then holds
a ``{column}`` placeholder.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDateTime, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from niimdesk.gui.merge_widgets import BOUND_STYLE, BOUND_TIP, ElementContext, table_icon
from niimdesk.render import merge, qrdata
from niimdesk.render.label import QrElement

MIN_MODULE_MM = 0.4  # smaller QR dots are hard to scan from a thermal label
EXAMPLE_PASSWORD = "Beispiel-Passwort"

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


def _default(f: qrdata.Field) -> str:
    if f.kind == "datetime":
        return _iso_now_plus(1 if f.key == "end" else 0)
    return f.default


def _with_button(widget: QWidget, button: QToolButton) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(2)
    row.addWidget(widget, 1)
    row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
    return host


class QrContentEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._element: QrElement | None = None
        self._loading = False
        self._context = ElementContext()

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

        self._bind_all = QPushButton()
        self._bind_all.setIcon(table_icon())
        self._bind_all.clicked.connect(self._toggle_all)
        layout.addWidget(self._bind_all)

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

    def set_context(self, context: ElementContext) -> None:
        self._context = context

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
        resolved = self._context.resolve(element)
        open_columns = list(dict.fromkeys(n for s in merge.slots(resolved) for n in merge.placeholders(s.get())))
        if open_columns:
            self._info.setText(
                "<span style='color:gray'>Aus der Tabelle: " + ", ".join(open_columns)
                + ". Die Punktgröße steht fest, sobald eine Tabelle geöffnet ist.</span>"
            )
            try:
                self._preview.setPlainText(resolved.payload())
            except (ValueError, KeyError):
                self._preview.setPlainText("")
            return
        if resolved.validate():
            self._preview.setPlainText("")
            self._info.setText("")
            return
        self._preview.setPlainText(resolved.payload())
        info = resolved.module_info()
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

    def _set_value(self, key: str, value: str) -> None:
        e = self._element
        assert e is not None
        if e.content_type == "text":
            e.data = value
        else:
            e.values[key] = value

    def _store(self, key: str, value: str) -> None:
        if self._loading or self._element is None or self._value(key) == value:
            return
        self._set_value(key, value)
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
                e.values[f.key] = _default(f)
            elif f.default and f.key not in e.values:
                e.values[f.key] = f.default
        self._rebuild()
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

    def _rebuild(self) -> None:
        if self._element is None:
            return
        self._loading = True
        try:
            self._build_fields()
            self._sync_level()
        finally:
            self._loading = False
        self.refresh_info()

    def _build_fields(self) -> None:
        while self._fields.rowCount():
            self._fields.removeRow(0)
        qr_type = self._qr_type()
        self._notes.setText(qr_type.notes)
        self._notes.setVisible(bool(qr_type.notes))
        for f in qr_type.fields:
            self._add_field(f)
        if self._all_bound():
            self._bind_all.setText("Alle Felder wieder fest eingeben")
            self._bind_all.setToolTip("Die Felder bekommen wieder feste Werte (aus der Beispielzeile)")
        else:
            self._bind_all.setText("Alle Felder aus Tabelle (Seriendruck)")
            self._bind_all.setToolTip(
                "Jedes Feld bekommt eine eigene Spalte in der Tabelle. Einzelne Felder schaltest du mit "
                "dem Tabellen-Symbol daneben um."
            )

    # --- table binding -----------------------------------------------------

    def _is_bound(self, f: qrdata.Field) -> bool:
        return merge.PLACEHOLDER.search(self._value(f.key)) is not None

    def _all_bound(self) -> bool:
        return all(self._is_bound(f) for f in self._qr_type().fields)

    def _bind(self, f: qrdata.Field) -> None:
        current = self._value(f.key) or f.default
        if merge.PLACEHOLDER.search(current):
            return
        name = self._context.unique_column(f.column_name)
        if f.kind == "password":  # no real password in the example row of the table
            self._context.sample[name] = EXAMPLE_PASSWORD
        elif current:
            self._context.sample[name] = merge.to_table_value(f, current)
        self._set_value(f.key, "{" + name + "}")

    def _unbind(self, f: qrdata.Field) -> None:
        current = self._value(f.key)
        names = merge.placeholders(current)
        if not names:
            return
        example = merge.fill_text(current, merge.lookup(self._context.sample))
        example = merge.PLACEHOLDER.sub("", example).strip() if f.kind != "multiline" else merge.PLACEHOLDER.sub("", example)
        if f.kind in ("choice", "check", "datetime"):
            value, error = merge.from_table_value(f, example)
            restored = value if example and not error else _default(f)
        else:
            restored = example
        self._set_value(f.key, restored)

    def _on_bind_toggled(self, f: qrdata.Field, on: bool) -> None:
        if self._loading or self._element is None:
            return
        self._bind(f) if on else self._unbind(f)
        self._binding_changed()

    def _toggle_all(self) -> None:
        if self._element is None:
            return
        unbind = self._all_bound()
        for f in self._qr_type().fields:
            self._unbind(f) if unbind else self._bind(f)
        self._binding_changed()

    def _binding_changed(self) -> None:
        self.changed.emit()
        # the clicked button belongs to the rows that are rebuilt, so rebuild after the click
        QTimer.singleShot(0, self._rebuild)

    # --- field widgets -----------------------------------------------------

    def _bind_button(self, f: qrdata.Field, bound: bool) -> QToolButton:
        button = QToolButton()
        button.setIcon(table_icon())
        button.setCheckable(True)
        button.setChecked(bound)
        button.setAutoRaise(True)
        button.setToolTip("Wieder fest eingeben" if bound else "Wert aus einer Tabellenspalte holen (Seriendruck)")
        button.toggled.connect(lambda on: self._on_bind_toggled(f, on))
        return button

    def _add_field(self, f: qrdata.Field) -> None:
        raw = self._value(f.key)
        bound = merge.PLACEHOLDER.search(raw) is not None
        value = raw or f.default
        key = f.key
        button = self._bind_button(f, bound)

        if bound:
            if f.kind == "multiline":
                w = QPlainTextEdit(value)
                w.setFixedHeight(48)
                w.textChanged.connect(lambda: self._store(key, w.toPlainText()))
            else:
                w = QLineEdit(value)
                w.textChanged.connect(lambda text: self._store(key, text))
            w.setStyleSheet(BOUND_STYLE)
            w.setToolTip(BOUND_TIP)
            self._fields.addRow(f.label, _with_button(w, button))
        elif f.kind == "multiline":
            w = QPlainTextEdit()
            w.setFixedHeight(64)
            w.setPlaceholderText(f.placeholder)
            w.setPlainText(value)
            w.textChanged.connect(lambda: self._store(key, w.toPlainText()))
            self._fields.addRow(f.label, _with_button(w, button))
        elif f.kind == "choice":
            w = _combo(list(f.choices))
            w.setCurrentIndex(max(w.findData(value), 0))
            w.currentIndexChanged.connect(lambda _: self._store(key, w.currentData()))
            self._fields.addRow(f.label, _with_button(w, button))
        elif f.kind == "check":
            w = QCheckBox(f.label)
            w.setChecked(value == "1")
            w.toggled.connect(lambda checked: self._store(key, "1" if checked else "0"))
            self._fields.addRow(_with_button(w, button))
        elif f.kind == "datetime":
            w = QDateTimeEdit()
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy HH:mm")
            parsed = QDateTime.fromString(value, "yyyy-MM-ddTHH:mm")
            w.setDateTime(parsed if parsed.isValid() else QDateTime.currentDateTime())
            w.dateTimeChanged.connect(lambda dt: self._store(key, dt.toString("yyyy-MM-ddTHH:mm")))
            self._fields.addRow(f.label, _with_button(w, button))
        else:
            w = QLineEdit(value)
            w.setPlaceholderText(f.placeholder)
            w.textChanged.connect(lambda text: self._store(key, text))
            self._fields.addRow(f.label, _with_button(w, button))
