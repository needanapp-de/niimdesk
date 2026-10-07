"""Main window: label settings, element list, preview canvas, properties and printing."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from niimdesk import __version__
from niimdesk.config import Config
from niimdesk.gui.canvas import LabelCanvas
from niimdesk.gui.device_dialog import DeviceDialog
from niimdesk.gui.properties import PropertyPanel, combo, mm_spin, select_data
from niimdesk.gui.worker import PrinterWorker
from niimdesk.models import DEFAULT_MODEL, PrinterModel
from niimdesk.protocol.client import PrinterInfo
from niimdesk.protocol.commands import LABEL_TYPE_NAMES
from niimdesk.protocol.parsers import Heartbeat, RfidInfo
from niimdesk.render.label import (
    BarcodeElement,
    Element,
    ImageElement,
    Label,
    QrElement,
    RectElement,
    TextElement,
    print_image,
    render,
    testpage_label,
)

LABEL_PRESETS = [(50, 30), (50, 20), (40, 30), (40, 20), (30, 20), (30, 15), (25, 15), (20, 10)]
IMAGE_FILTER = "Bilder (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)"
TEMPLATE_FILTER = "niimdesk-Vorlagen (*.json)"


class MainWindow(QMainWindow):
    def __init__(self, worker: PrinterWorker, config: Config) -> None:
        super().__init__()
        self.worker = worker
        self.config = config
        self.label = self._new_label()
        self.path: Path | None = None
        self.dirty = False

        self.printer_info: PrinterInfo | None = None
        self.heartbeat_data: Heartbeat | None = None
        self.rfid_info: RfidInfo | None = None
        self.connecting = False
        self.printing = False
        self._user_initiated_connect = False
        self._asked_rolls: set[str] = set()

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._render)

        self._build_ui()
        self._build_menus()
        self._connect_worker()
        self._load_label_into_ui()
        self._update_printer_ui()
        self._update_roll_ui()
        self.resize(1280, 760)
        self.canvas.setFocus()

        if config.auto_connect and config.printer_address:
            QTimer.singleShot(300, lambda: self._connect_to(config.printer_address, user=False))

    # --- model helpers -----------------------------------------------------

    def _new_label(self) -> Label:
        w, h = self.config.label_width_mm, self.config.label_height_mm
        return Label(
            width_mm=w,
            height_mm=h,
            density=self.config.density,
            label_type=self.config.label_type,
            elements=[
                TextElement(
                    x=2, y=2, width=w - 4, height=h - 4, text="Mein Etikett", size_pt=20,
                    bold=True, align="center", valign="middle", fit=True,
                )
            ],
        )

    @property
    def model(self) -> PrinterModel:
        if self.printer_info and self.printer_info.model:
            return self.printer_info.model
        return DEFAULT_MODEL

    @property
    def printhead_px(self) -> int:
        return (self.printer_info.printhead_width if self.printer_info else None) or self.model.printhead_pixels

    # --- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        toolbar = QToolBar("Drucker")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.connect_button = QPushButton("Drucker verbinden …")
        self.connect_button.clicked.connect(self._on_connect_button)
        toolbar.addWidget(self.connect_button)
        self.printer_status = QLabel()
        self.printer_status.setTextFormat(Qt.TextFormat.RichText)
        self.printer_status.setContentsMargins(12, 0, 12, 0)
        toolbar.addWidget(self.printer_status)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())

        self.canvas = LabelCanvas()
        self.canvas.selection_changed.connect(self._on_canvas_selection)
        self.canvas.geometry_changed.connect(self._on_canvas_geometry)
        self.canvas.delete_requested.connect(self.delete_element)
        splitter.addWidget(self.canvas)

        self.properties = PropertyPanel()
        self.properties.changed.connect(self._on_property_changed)
        self.properties.replace_image_requested.connect(self.replace_image)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.properties)
        scroll.setMinimumWidth(320)
        splitter.addWidget(scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 660, 340])
        self.setCentralWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(260)
        layout = QVBoxLayout(panel)

        # label settings
        group = QGroupBox("Etikett")
        form = QFormLayout(group)
        self.roll_box = QLabel()
        self.roll_box.setWordWrap(True)
        self.roll_box.setTextFormat(Qt.TextFormat.RichText)
        form.addRow(self.roll_box)
        self.roll_button = QPushButton("Andere Größe zuordnen …")
        self.roll_button.setToolTip("Falls die gemerkte Größe für diese Etikettenrolle nicht stimmt")
        self.roll_button.clicked.connect(self.assign_roll_size)
        form.addRow(self.roll_button)
        self.preset_combo = combo([(f"{w} × {h} mm", (w, h)) for w, h in LABEL_PRESETS] + [("Eigene Größe", None)])
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        form.addRow("Vorlage", self.preset_combo)
        self.width_spin = mm_spin(10, 60)
        self.height_spin = mm_spin(5, 300)
        self.width_spin.valueChanged.connect(lambda v: self._on_size(width=v))
        self.height_spin.valueChanged.connect(lambda v: self._on_size(height=v))
        form.addRow("Breite", self.width_spin)
        form.addRow("Höhe", self.height_spin)
        self.type_combo = combo([(LABEL_TYPE_NAMES[t], int(t)) for t in DEFAULT_MODEL.label_types])
        self.type_combo.currentIndexChanged.connect(self._on_label_type)
        form.addRow("Etikettentyp", self.type_combo)
        self.density_spin = QSpinBox()
        self.density_spin.setRange(DEFAULT_MODEL.density_min, DEFAULT_MODEL.density_max)
        self.density_spin.setToolTip("Höher = dunkler. Standard beim B1: 3")
        self.density_spin.valueChanged.connect(self._on_density)
        form.addRow("Druckdichte", self.density_spin)
        layout.addWidget(group)

        # elements
        group = QGroupBox("Elemente")
        v = QVBoxLayout(group)
        grid = QGridLayout()
        adders = [
            ("Text", lambda: self.add_element(TextElement())),
            ("QR-Code", lambda: self.add_element(QrElement())),
            ("Barcode", lambda: self.add_element(BarcodeElement())),
            ("Bild …", self.add_image),
            ("Rahmen / Linie", lambda: self.add_element(RectElement())),
        ]
        for i, (text, slot) in enumerate(adders):
            button = QPushButton(f"+ {text}")
            button.clicked.connect(slot)
            grid.addWidget(button, i // 2, i % 2)
        v.addLayout(grid)
        self.element_list = QListWidget()
        self.element_list.currentRowChanged.connect(self._on_list_selection)
        v.addWidget(self.element_list, 1)
        row = QHBoxLayout()
        for text, tip, slot in (
            ("Kopie", "Duplizieren", self.duplicate_element),
            ("▲", "Nach hinten", lambda: self.move_element(-1)),
            ("▼", "Nach vorne", lambda: self.move_element(1)),
            ("Löschen", "Element löschen (Entf)", self.delete_element),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        layout.addWidget(group, 1)

        # printing
        group = QGroupBox("Drucken")
        v = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Kopien"))
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 999)
        row.addWidget(self.copies_spin, 1)
        v.addLayout(row)
        self.print_button = QPushButton("Drucken")
        self.print_button.setMinimumHeight(40)
        font = self.print_button.font()
        font.setBold(True)
        self.print_button.setFont(font)
        self.print_button.clicked.connect(self.print_label)
        v.addWidget(self.print_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.worker.cancel_print)
        v.addWidget(self.cancel_button)
        layout.addWidget(group)

        return panel

    def _offset_spin(self, value: float, attr: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-5, 5)
        spin.setDecimals(2)
        spin.setSingleStep(0.25)
        spin.setSuffix(" mm")
        spin.setKeyboardTracking(False)
        spin.setValue(value)

        def changed(v: float) -> None:
            setattr(self.config, attr, round(v, 3))
            self.config.save()

        spin.valueChanged.connect(changed)
        return spin

    def _build_menus(self) -> None:
        def action(menu, text, slot, shortcut=None) -> QAction:  # noqa: ANN001
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m = self.menuBar().addMenu("&Datei")
        action(m, "Neu", self.new_label, QKeySequence.StandardKey.New)
        action(m, "Öffnen …", self.open_label, QKeySequence.StandardKey.Open)
        action(m, "Speichern", self.save_label, QKeySequence.StandardKey.Save)
        action(m, "Speichern unter …", self.save_label_as, QKeySequence.StandardKey.SaveAs)
        m.addSeparator()
        action(m, "Als PNG exportieren …", self.export_png)
        m.addSeparator()
        action(m, "Beenden", self.close, QKeySequence.StandardKey.Quit)

        m = self.menuBar().addMenu("D&rucker")
        action(m, "Verbinden …", self.show_device_dialog)
        self.disconnect_action = action(m, "Trennen", self.worker.disconnect_printer)
        m.addSeparator()
        self.print_action = action(m, "Drucken", self.print_label, QKeySequence.StandardKey.Print)
        self.testpage_action = action(m, "Testetikett drucken", self.print_testpage)
        m.addSeparator()
        action(m, "Druckversatz …", self.show_offset_dialog)

        m = self.menuBar().addMenu("&Hilfe")
        action(m, "Über niimdesk", self.show_about)

    def _connect_worker(self) -> None:
        w = self.worker
        w.connecting.connect(self._on_connecting)
        w.connected.connect(self._on_connected)
        w.connect_failed.connect(self._on_connect_failed)
        w.disconnected.connect(self._on_disconnected)
        w.heartbeat.connect(self._on_heartbeat)
        w.rfid.connect(self._on_rfid)
        w.print_progress.connect(self._on_print_progress)
        w.print_finished.connect(self._on_print_finished)
        w.print_failed.connect(self._on_print_failed)
        w.printer_error.connect(lambda msg: self.statusBar().showMessage(f"Drucker meldet: {msg}", 8000))

    # --- label <-> UI ------------------------------------------------------

    def _load_label_into_ui(self) -> None:
        for widget, value in (
            (self.width_spin, self.label.width_mm),
            (self.height_spin, self.label.height_mm),
            (self.density_spin, self.label.density),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.type_combo.blockSignals(True)
        select_data(self.type_combo, int(self.label.label_type))
        self.type_combo.blockSignals(False)
        self._sync_preset()
        self.canvas.set_label(self.label)
        self._refresh_list()
        self.properties.set_element(None)
        self._schedule_render()
        self._update_title()

    def _sync_preset(self) -> None:
        size = (self.label.width_mm, self.label.height_mm)
        index = next(
            (i for i, p in enumerate(LABEL_PRESETS) if p == size), self.preset_combo.count() - 1
        )
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def _refresh_list(self) -> None:
        current = self.canvas.selected()
        self.element_list.blockSignals(True)
        self.element_list.clear()
        for element in self.label.elements:
            text = element.summary()
            if element.validate():
                text = "⚠ " + text
            self.element_list.addItem(text)
        self.element_list.setCurrentRow(current)
        self.element_list.blockSignals(False)

    def _schedule_render(self) -> None:
        self._render_timer.start()

    def _render(self) -> None:
        self.canvas.set_printer_geometry(self.model.dpi, self.printhead_px)
        self.canvas.set_preview(render(self.label, self.model.dpi))

    def _changed(self, refresh_list: bool = False) -> None:
        if not self.dirty:
            self.dirty = True
            self._update_title()
        if refresh_list:
            self._refresh_list()
        self._schedule_render()

    def _update_title(self) -> None:
        name = self.path.name if self.path else "Neues Etikett"
        self.setWindowTitle(f"{name}{' *' if self.dirty else ''} – niimdesk")

    # --- label settings ----------------------------------------------------

    def _on_preset(self, _index: int) -> None:
        size = self.preset_combo.currentData()
        if size is None:
            return
        self.width_spin.setValue(size[0])
        self.height_spin.setValue(size[1])

    def _on_size(self, width: float | None = None, height: float | None = None) -> None:
        if width is not None:
            self.label.width_mm = round(width, 2)
            self.config.label_width_mm = self.label.width_mm
        if height is not None:
            self.label.height_mm = round(height, 2)
            self.config.label_height_mm = self.label.height_mm
        self.config.save()
        self._sync_preset()
        self.canvas.update()
        self._changed()

    def _on_label_type(self, _index: int) -> None:
        self.label.label_type = self.type_combo.currentData()
        self.config.label_type = self.label.label_type
        self.config.save()
        self._changed()

    def _on_density(self, value: int) -> None:
        self.label.density = value
        self.config.density = value
        self.config.save()
        self._changed()

    # --- elements ----------------------------------------------------------

    def _selected_element(self) -> Element | None:
        i = self.canvas.selected()
        return self.label.elements[i] if 0 <= i < len(self.label.elements) else None

    def add_element(self, element: Element) -> None:
        # keep new elements inside the label
        element.width = min(element.width, max(self.label.width_mm - 4, 1))
        element.height = min(element.height, max(self.label.height_mm - 4, 1))
        if isinstance(element, QrElement):
            element.width = element.height = min(element.width, element.height)
        # cascade from the top left corner of the printable area so new elements don't hide each other
        margin = 2 + max(0.0, (self.label.width_mm - self.printhead_px / (self.model.dpi / 25.4)) / 2)
        step = 2 * (len(self.label.elements) % 5)
        element.x = round(min(margin + step, max(self.label.width_mm - element.width, 0)), 1)
        element.y = round(min(2 + step, max(self.label.height_mm - element.height, 0)), 1)
        self.label.elements.append(element)
        self._changed(refresh_list=True)
        self.canvas.set_selected(len(self.label.elements) - 1)

    def add_image(self) -> None:
        path = self._ask_image()
        if not path:
            return
        try:
            element = ImageElement.from_file(path)
        except OSError as e:
            QMessageBox.warning(self, "Bild", f"Bild kann nicht geladen werden:\n{e}")
            return
        self._fit_image(element)
        self.add_element(element)

    def replace_image(self) -> None:
        element = self._selected_element()
        if not isinstance(element, ImageElement):
            return
        path = self._ask_image()
        if not path:
            return
        try:
            new = ImageElement.from_file(path)
        except OSError as e:
            QMessageBox.warning(self, "Bild", f"Bild kann nicht geladen werden:\n{e}")
            return
        element.name, element.png_base64 = new.name, new.png_base64
        self.properties.set_element(element)
        self._changed(refresh_list=True)

    def _ask_image(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "Bild auswählen", self.config.last_directory, IMAGE_FILTER)
        if path:
            self.config.last_directory = str(Path(path).parent)
            self.config.save()
        return path

    def _fit_image(self, element: ImageElement) -> None:
        size = element.source_size() or (1, 1)
        max_w, max_h = self.label.width_mm - 4, self.label.height_mm - 4
        scale = min(max_w / size[0], max_h / size[1])
        element.width = round(size[0] * scale, 1)
        element.height = round(size[1] * scale, 1)

    def delete_element(self) -> None:
        i = self.canvas.selected()
        if not 0 <= i < len(self.label.elements):
            return
        del self.label.elements[i]
        self.canvas.set_selected(min(i, len(self.label.elements) - 1))
        self._changed(refresh_list=True)

    def duplicate_element(self) -> None:
        element = self._selected_element()
        if element is None:
            return
        clone = copy.deepcopy(element)
        clone.x, clone.y = round(clone.x + 2, 1), round(clone.y + 2, 1)
        self.label.elements.append(clone)
        self._changed(refresh_list=True)
        self.canvas.set_selected(len(self.label.elements) - 1)

    def move_element(self, direction: int) -> None:
        i = self.canvas.selected()
        j = i + direction
        if not (0 <= i < len(self.label.elements) and 0 <= j < len(self.label.elements)):
            return
        elements = self.label.elements
        elements[i], elements[j] = elements[j], elements[i]
        self.canvas.set_selected(j)
        self._changed(refresh_list=True)

    def _on_canvas_selection(self, index: int) -> None:
        self.element_list.blockSignals(True)
        self.element_list.setCurrentRow(index)
        self.element_list.blockSignals(False)
        self.properties.set_element(self._selected_element())

    def _on_list_selection(self, row: int) -> None:
        self.canvas.set_selected(row)

    def _on_canvas_geometry(self, _index: int) -> None:
        self.properties.refresh_geometry()
        self._changed()

    def _on_property_changed(self) -> None:
        i = self.canvas.selected()
        element = self._selected_element()
        if element is not None and (item := self.element_list.item(i)) is not None:
            item.setText(("⚠ " if element.validate() else "") + element.summary())
        self.canvas.update()
        self._changed()

    # --- files -------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Ungespeicherte Änderungen",
            "Das Etikett wurde geändert. Änderungen speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_label()
        return answer == QMessageBox.StandardButton.Discard

    def new_label(self) -> None:
        if not self._confirm_discard():
            return
        self.label, self.path, self.dirty = self._new_label(), None, False
        self._load_label_into_ui()
        self._apply_roll()

    def open_label(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Vorlage öffnen", self.config.last_directory, TEMPLATE_FILTER)
        if not path:
            return
        try:
            label = Label.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as e:
            QMessageBox.warning(self, "Öffnen", f"Vorlage kann nicht geöffnet werden:\n{e}")
            return
        self.config.last_directory = str(Path(path).parent)
        self.config.save()
        self.label, self.path, self.dirty = label, Path(path), False
        self._load_label_into_ui()
        self._apply_roll()

    def save_label(self) -> bool:
        if self.path is None:
            return self.save_label_as()
        try:
            self.path.write_text(json.dumps(self.label.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Speichern", f"Speichern fehlgeschlagen:\n{e}")
            return False
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Gespeichert: {self.path}", 4000)
        return True

    def save_label_as(self) -> bool:
        start = str(self.path or Path(self.config.last_directory or Path.home()) / "etikett.json")
        path, _ = QFileDialog.getSaveFileName(self, "Vorlage speichern", start, TEMPLATE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".json"
        self.path = Path(path)
        self.config.last_directory = str(self.path.parent)
        self.config.save()
        return self.save_label()

    def export_png(self) -> None:
        start = str(Path(self.config.last_directory or Path.home()) / "etikett.png")
        path, _ = QFileDialog.getSaveFileName(self, "Als PNG exportieren", start, "PNG-Bild (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            render(self.label, self.model.dpi).save(path, dpi=(self.model.dpi, self.model.dpi))
        except OSError as e:
            QMessageBox.warning(self, "Export", f"Export fehlgeschlagen:\n{e}")
            return
        self.statusBar().showMessage(f"Exportiert: {path}", 4000)

    # --- printer connection ------------------------------------------------

    def _on_connect_button(self) -> None:
        if self.printer_info is not None:
            self.worker.disconnect_printer()
        else:
            self.show_device_dialog()

    def show_device_dialog(self) -> None:
        dialog = DeviceDialog(self.worker, self.config.auto_connect, self)
        if dialog.exec() != DeviceDialog.DialogCode.Accepted or (printer := dialog.selected()) is None:
            return
        self.config.printer_address = printer.address
        self.config.printer_name = printer.name
        self.config.auto_connect = dialog.auto_connect.isChecked()
        self.config.save()
        self._connect_to(printer.device, user=True)

    def _connect_to(self, target, user: bool) -> None:  # noqa: ANN001 - address or BLEDevice
        self._user_initiated_connect = user
        self.connecting = True
        self._update_printer_ui()
        self.worker.connect_printer(target)

    def _on_connecting(self, name: str) -> None:
        self.connecting = True
        self.printer_status.setText(f"<span style='color:#d0a000'>●</span> Verbinde mit {name} …")
        self._update_printer_ui(status=False)

    def _on_connected(self, info: PrinterInfo) -> None:
        self.connecting = False
        self.printer_info = info
        self.statusBar().showMessage(f"Verbunden mit {info.model_name}", 4000)
        if info.model and not info.model.supported:
            QMessageBox.warning(
                self, "Drucker", f"Der {info.model.name} wird von niimdesk noch nicht unterstützt. Drucken ist deaktiviert."
            )
        elif info.model is None:
            QMessageBox.warning(
                self, "Drucker", f"Unbekanntes Druckermodell (ID {info.model_id}). Es werden B1-Einstellungen verwendet."
            )
        self._update_printer_ui()
        self._schedule_render()

    def _on_connect_failed(self, message: str) -> None:
        self.connecting = False
        self._update_printer_ui()
        if self._user_initiated_connect:
            QMessageBox.warning(self, "Verbindung fehlgeschlagen", message)
        else:
            self.statusBar().showMessage(f"Automatisches Verbinden fehlgeschlagen: {message}", 10000)

    def _on_disconnected(self) -> None:
        was_printing = self.printing
        self.printer_info = None
        self.heartbeat_data = None
        self.rfid_info = None
        self.connecting = False
        self._update_printer_ui()
        self._update_roll_ui()
        if not was_printing:
            self.statusBar().showMessage("Drucker getrennt", 4000)

    def _on_heartbeat(self, hb: Heartbeat) -> None:
        self.heartbeat_data = hb
        self._update_printer_ui()

    def _on_rfid(self, info: RfidInfo) -> None:
        self.rfid_info = info
        self._update_printer_ui()
        self._apply_roll()

    # --- label roll (RFID) -------------------------------------------------

    def _detected_roll(self) -> tuple[str, tuple[float, float] | None] | None:
        """Barcode of the inserted original roll and its remembered size."""
        info = self.rfid_info
        if self.printer_info is None or info is None or not info.tag_present or not info.barcode:
            return None
        return info.barcode, self.config.roll_size(info.barcode)

    def _apply_roll(self) -> None:
        """Take label size and type from the inserted roll."""
        roll = self._detected_roll()
        if roll is not None and not self.printing:
            barcode, size = roll
            if size is None and barcode not in self._asked_rolls:
                self._asked_rolls.add(barcode)
                size = self._ask_roll_size(barcode)
                if size is not None:
                    self.config.remember_roll(barcode, *size)
            if size is not None:
                if (self.label.width_mm, self.label.height_mm) != size:
                    self._set_label_size(*size)
                    self.statusBar().showMessage(
                        f"Etikettengröße an die eingelegte Rolle angepasst: {size[0]:g} × {size[1]:g} mm", 8000
                    )
                label_type = self.rfid_info.label_type if self.rfid_info else 0
                if self.type_combo.findData(label_type) >= 0 and label_type != self.label.label_type:
                    select_data(self.type_combo, label_type)
        self._update_roll_ui()

    def _set_label_size(self, width: float, height: float) -> None:
        self.label.width_mm, self.label.height_mm = width, height
        self.config.label_width_mm, self.config.label_height_mm = width, height
        self.config.save()
        for spin, value in ((self.width_spin, width), (self.height_spin, height)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._sync_preset()
        self.canvas.update()
        if self.path is not None:
            self._changed()
        else:
            self._schedule_render()

    def _update_roll_ui(self) -> None:
        roll = self._detected_roll()
        locked = roll is not None and roll[1] is not None
        for widget in (self.preset_combo, self.width_spin, self.height_spin, self.type_combo):
            widget.setEnabled(not locked)
        self.roll_button.setVisible(roll is not None)

        ok = "background: rgba(32,160,32,0.13); border: 1px solid rgba(32,160,32,0.55);"
        warn = "background: rgba(220,160,0,0.13); border: 1px solid rgba(220,160,0,0.6);"
        style = "border-radius: 4px; padding: 6px;"
        if locked:
            barcode, (w, h) = roll[0], roll[1]
            info = self.rfid_info
            type_name = self.type_combo.currentText()
            text = f"<b>✓ Etikettenrolle erkannt</b><br>{w:g} × {h:g} mm · {type_name}"
            if info and info.total_labels > 0:
                text += f"<br>{info.total_labels - info.used_labels} von {info.total_labels} Etiketten übrig"
            self.roll_box.setText(text)
            self.roll_box.setToolTip(f"Rolle {barcode}. Größe und Typ werden von der Rolle vorgegeben.")
            self.roll_box.setStyleSheet(ok + style)
            self.roll_button.setText("Andere Größe zuordnen …")
        elif roll is not None:
            self.roll_box.setText(f"<b>Rolle {roll[0]} erkannt</b><br>Größe unbekannt, bitte zuordnen.")
            self.roll_box.setStyleSheet(warn + style)
            self.roll_button.setText("Größe zuordnen …")
        elif self.printer_info is not None and self.rfid_info is not None:
            self.roll_box.setText("<b>Keine Original-Rolle erkannt</b><br>Größe und Typ bitte selbst einstellen.")
            self.roll_box.setStyleSheet(warn + style)
        else:
            self.roll_box.setText("Größe und Typ werden übernommen, sobald ein Drucker mit Original-Rolle verbunden ist.")
            self.roll_box.setStyleSheet("color: palette(mid);")

    def assign_roll_size(self) -> None:
        roll = self._detected_roll()
        if roll is None:
            return
        size = self._ask_roll_size(roll[0])
        if size is not None:
            self.config.remember_roll(roll[0], *size)
            self._apply_roll()

    def _ask_roll_size(self, barcode: str) -> tuple[float, float] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Neue Etikettenrolle")
        layout = QVBoxLayout(dialog)
        text = QLabel(
            f"Eine Etikettenrolle (Nr. {barcode}) wurde erkannt. Der Drucker meldet ihre Größe nicht. "
            "Welche Größe haben die Etiketten? niimdesk merkt sich das für diese Rolle."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        form = QFormLayout()
        presets = combo([(f"{w} × {h} mm", (w, h)) for w, h in LABEL_PRESETS] + [("Eigene Größe", None)])
        width, height = mm_spin(10, 60), mm_spin(5, 300)
        width.setValue(self.label.width_mm)
        height.setValue(self.label.height_mm)
        current = (self.label.width_mm, self.label.height_mm)
        presets.setCurrentIndex(next((i for i, p in enumerate(LABEL_PRESETS) if p == current), len(LABEL_PRESETS)))

        def on_preset() -> None:
            if (size := presets.currentData()) is not None:
                width.setValue(size[0])
                height.setValue(size[1])

        presets.currentIndexChanged.connect(on_preset)
        form.addRow("Größe", presets)
        form.addRow("Breite", width)
        form.addRow("Höhe", height)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return round(width.value(), 2), round(height.value(), 2)

    def show_offset_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Druckversatz")
        layout = QVBoxLayout(dialog)
        text = QLabel(
            "Nur nötig, wenn der Druck bei <b>allen</b> Etiketten deutlich (mehr als ca. 0,5 mm) in dieselbe "
            "Richtung verschoben sitzt. Kleinere Abweichungen schwanken von Etikett zu Etikett, weil die Rolle "
            "seitlich etwas Spiel hat, und lassen sich nicht wegkalibrieren."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        form = QFormLayout()
        x = self._offset_spin(self.config.offset_x_mm, "offset_x_mm")
        y = self._offset_spin(self.config.offset_y_mm, "offset_y_mm")
        form.addRow("Nach rechts", x)
        form.addRow("Nach unten", y)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        reset = buttons.addButton("Auf 0 setzen", QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(lambda: (x.setValue(0), y.setValue(0)))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _update_printer_ui(self, status: bool = True) -> None:
        connected = self.printer_info is not None
        can_print = connected and self.model.supported and not self.printing
        self.print_button.setEnabled(can_print)
        self.print_action.setEnabled(can_print)
        self.testpage_action.setEnabled(can_print)
        self.disconnect_action.setEnabled(connected)
        self.connect_button.setEnabled(not self.connecting and not self.printing)
        self.connect_button.setText("Trennen" if connected else "Drucker verbinden …")
        if status:
            self.printer_status.setText(self._status_html())

    def _status_html(self) -> str:
        if self.connecting:
            return "<span style='color:#d0a000'>●</span> Verbinde …"
        info = self.printer_info
        if info is None:
            return "<span style='color:gray'>●</span> Kein Drucker verbunden"

        parts = [f"<b>{info.model_name}</b>"]
        if info.serial:
            parts.append(info.serial)
        if info.software_version:
            parts.append(f"FW {info.software_version}")
        if info.battery_percent is not None:
            parts.append(f"Akku {info.battery_percent} %")
        if self.rfid_info and self.rfid_info.tag_present and self.rfid_info.total_labels > 0:
            left = self.rfid_info.total_labels - self.rfid_info.used_labels
            parts.append(f"{left} Etiketten übrig")

        warnings = []
        hb = self.heartbeat_data
        if hb and hb.lid_closed is False:
            warnings.append("Deckel offen")
        if hb and hb.paper_inserted is False:
            warnings.append("Kein Papier")
        elif self.rfid_info is not None and not self.rfid_info.tag_present:
            warnings.append("Keine Original-Etiketten erkannt")

        text = "<span style='color:#20a020'>●</span> " + " · ".join(parts)
        if warnings:
            text += " · <span style='color:#d03030'><b>" + ", ".join(warnings) + "</b></span>"
        return text

    # --- printing ----------------------------------------------------------

    def print_label(self) -> None:
        self._print(self.label, self.copies_spin.value())

    def print_testpage(self) -> None:
        label = testpage_label(self.label.width_mm, self.label.height_mm, self.printhead_px / (self.model.dpi / 25.4))
        label.density, label.label_type = self.label.density, self.label.label_type
        self._print(label, 1)

    def _print(self, label: Label, copies: int) -> None:
        if self.printing:
            return
        if self.printer_info is None:
            self.show_device_dialog()
            return

        errors = [e.validate() for e in label.elements if e.validate()]
        if errors:
            QMessageBox.warning(self, "Drucken", "Bitte zuerst korrigieren:\n\n" + "\n".join(errors))
            return

        problems = []
        hb = self.heartbeat_data
        if hb and hb.lid_closed is False:
            problems.append("Der Deckel ist offen.")
        if hb and hb.paper_inserted is False:
            problems.append("Es ist kein Papier eingelegt.")
        if self.rfid_info is not None and not self.rfid_info.tag_present:
            problems.append("Keine Original-Etikettenrolle erkannt. Der B1 druckt dann eventuell nur leere Etiketten.")
        if problems:
            answer = QMessageBox.question(self, "Drucken", "\n".join(problems) + "\n\nTrotzdem drucken?")
            if answer != QMessageBox.StandardButton.Yes:
                return

        image: Image.Image = print_image(
            label, self.model.dpi, self.printhead_px, self.config.offset_x_mm, self.config.offset_y_mm
        )
        self._set_printing(True)
        self._copies = copies
        self.worker.print_image(image, label.density, label.label_type, copies)

    def _set_printing(self, printing: bool) -> None:
        self.printing = printing
        self.progress.setVisible(printing)
        self.progress.setValue(0)
        self.progress.setFormat("Übertragung …")
        self.cancel_button.setVisible(printing)
        self._update_printer_ui()

    def _on_print_progress(self, stage: str, fraction: float) -> None:
        if stage == "transfer":
            self.progress.setValue(round(fraction * 40))
            self.progress.setFormat("Übertragung … %p %")
        else:
            self.progress.setValue(40 + round(fraction * 60))
            self.progress.setFormat("Druck … %p %")

    def _on_print_finished(self) -> None:
        self._set_printing(False)
        n = getattr(self, "_copies", 1)
        self.statusBar().showMessage(f"{n} Etikett{'en' if n != 1 else ''} gedruckt", 6000)

    def _on_print_failed(self, message: str) -> None:
        self._set_printing(False)
        if message == "Druck abgebrochen":
            self.statusBar().showMessage(message, 6000)
        else:
            QMessageBox.warning(self, "Druckfehler", message)

    # --- misc --------------------------------------------------------------

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "Über niimdesk",
            f"<b>niimdesk {__version__}</b><br>Etiketten für den NIIMBOT B1 per Bluetooth drucken.<br><br>"
            "Das Druckerprotokoll basiert auf <a href='https://github.com/MultiMote/niimbluelib'>niimbluelib</a> "
            "von MultiMote (MIT-Lizenz).",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.printing:
            answer = QMessageBox.question(self, "Beenden", "Es wird gerade gedruckt. Trotzdem beenden?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if not self._confirm_discard():
            event.ignore()
            return
        self.config.save()
        event.accept()
