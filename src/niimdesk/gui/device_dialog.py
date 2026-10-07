"""Dialog to find and pick a printer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from niimdesk.gui.worker import PrinterWorker
from niimdesk.transport.ble import FoundPrinter

HINT = (
    "Drucker einschalten und in die Nähe stellen. Ist er mit der Handy-App verbunden, "
    "dort zuerst trennen, sonst ist er für den PC unsichtbar. Unter Windows den Drucker "
    "nicht in den Bluetooth-Einstellungen koppeln."
)


class DeviceDialog(QDialog):
    def __init__(self, worker: PrinterWorker, auto_connect: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Drucker verbinden")
        self.setMinimumWidth(440)
        self._worker = worker
        self._printers: list[FoundPrinter] = []

        layout = QVBoxLayout(self)
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self.accept())
        self._list.currentRowChanged.connect(lambda _: self._update_buttons())
        layout.addWidget(self._list, 1)

        self._status = QLabel()
        layout.addWidget(self._status)

        self.auto_connect = QCheckBox("Beim Start automatisch mit diesem Drucker verbinden")
        self.auto_connect.setChecked(auto_connect)
        layout.addWidget(self.auto_connect)

        buttons = QDialogButtonBox()
        self._rescan = QPushButton("Erneut suchen")
        self._rescan.clicked.connect(self.start_scan)
        buttons.addButton(self._rescan, QDialogButtonBox.ButtonRole.ActionRole)
        self._ok = buttons.addButton("Verbinden", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        worker.scan_finished.connect(self._on_results)
        worker.scan_failed.connect(self._on_failed)
        self.finished.connect(self._disconnect_signals)

        self._update_buttons()
        self.start_scan()

    def selected(self) -> FoundPrinter | None:
        row = self._list.currentRow()
        return self._printers[row] if 0 <= row < len(self._printers) else None

    def start_scan(self) -> None:
        self._rescan.setEnabled(False)
        self._status.setText("Suche läuft …")
        self._worker.scan(5.0)

    def _on_results(self, printers: list[FoundPrinter]) -> None:
        self._printers = printers
        self._list.clear()
        for p in printers:
            rssi = f"{p.rssi} dBm" if p.rssi is not None else "?"
            note = "" if p.is_b1 else "  (kein B1, evtl. nicht unterstützt)"
            item = QListWidgetItem(f"{p.name or 'Unbenannt'}   ·   {p.address}   ·   Signal {rssi}{note}")
            item.setData(Qt.ItemDataRole.UserRole, p.address)
            self._list.addItem(item)
        if printers:
            self._list.setCurrentRow(0)
            self._status.setText(f"{len(printers)} Drucker gefunden.")
        else:
            self._status.setText("Kein Drucker gefunden. Ist er eingeschaltet und nicht mit dem Handy verbunden?")
        self._rescan.setEnabled(True)
        self._update_buttons()

    def _on_failed(self, message: str) -> None:
        self._status.setText(message)
        self._rescan.setEnabled(True)

    def _update_buttons(self) -> None:
        self._ok.setEnabled(self.selected() is not None)

    def _disconnect_signals(self) -> None:
        self._worker.scan_finished.disconnect(self._on_results)
        self._worker.scan_failed.disconnect(self._on_failed)
