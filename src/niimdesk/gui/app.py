"""GUI entry point."""

from __future__ import annotations

import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from niimdesk import __version__
from niimdesk.config import Config, config_path


def app_icon() -> QIcon:
    """A small label drawn at runtime, so no image files are needed."""
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 64
        p.setPen(QPen(QColor("#1f2937"), max(1.0, 3 * s)))
        p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(5 * s, 13 * s, 54 * s, 38 * s), 6 * s, 6 * s)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1f2937"))
        for y in (21, 29):
            p.drawRect(QRectF(11 * s, y * s, 22 * s, 4 * s))
        p.drawRect(QRectF(11 * s, 37 * s, 14 * s, 4 * s))
        p.setBrush(QColor("#2563eb"))
        p.drawRect(QRectF(39 * s, 21 * s, 14 * s, 14 * s))
        p.end()
        icon.addPixmap(pixmap)
    return icon


def setup_logging() -> None:
    """Log to the console (if there is one) and to niimdesk.log next to the config file.

    The packaged Windows GUI has no console, so the file is the only place to see what happened.
    """
    level = logging.DEBUG if os.environ.get("NIIMDESK_DEBUG") else logging.INFO
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    log_file = config_path().parent / "niimdesk.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=1, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    logging.getLogger("bleak").setLevel(max(level, logging.INFO))


def main() -> None:
    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("niimdesk")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())

    # imported late so that the QApplication exists before any widget module is loaded
    from niimdesk.gui.main_window import MainWindow
    from niimdesk.gui.worker import PrinterWorker

    worker = PrinterWorker()
    window = MainWindow(worker, Config.load())
    window.show()

    # Ctrl+C / kill: leave the event loop so the printer gets disconnected cleanly below.
    # The timer lets the Python interpreter run its signal handlers while Qt is waiting.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: app.exit(0))
    wakeup = QTimer()
    wakeup.timeout.connect(lambda: None)
    wakeup.start(300)

    code = app.exec()
    worker.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
