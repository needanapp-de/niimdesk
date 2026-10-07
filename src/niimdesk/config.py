"""Persistent settings shared by GUI and CLI (JSON in the user's config directory)."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)


def config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "niimdesk" / "config.json"


@dataclass
class Config:
    # calibration: shifts the print to compensate the printer's label positioning (mm)
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    # last used printer
    printer_address: str = ""
    printer_name: str = ""
    auto_connect: bool = True
    # defaults for new labels
    label_width_mm: float = 50.0
    label_height_mm: float = 30.0
    density: int = 3
    label_type: int = 1
    last_directory: str = ""
    # known label rolls: RFID barcode -> [width_mm, height_mm]; the B1 does not report the label size
    rolls: dict[str, list[float]] = field(default_factory=dict)

    def roll_size(self, barcode: str) -> tuple[float, float] | None:
        size = self.rolls.get(barcode)
        if isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) for v in size):
            return float(size[0]), float(size[1])
        return None

    def remember_roll(self, barcode: str, width_mm: float, height_mm: float) -> None:
        self.rolls[barcode] = [width_mm, height_mm]
        self.save()

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as e:
            log.warning("Cannot read %s: %s", path, e)
            return cls()
        config = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(config, f.name)
            if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if type(value) is type(default):
                setattr(config, f.name, value)
        return config

    def save(self) -> None:
        path = config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            log.warning("Cannot write %s: %s", path, e)
