"""Printer model metadata (values from niimbluelib and the official app config)."""

from __future__ import annotations

from dataclasses import dataclass

from niimdesk.protocol.commands import LabelType


@dataclass(frozen=True)
class PrinterModel:
    name: str
    model_ids: tuple[int, ...]
    dpi: int
    printhead_pixels: int
    label_types: tuple[LabelType, ...]
    density_min: int
    density_max: int
    density_default: int
    supported: bool  # print task implemented and tested in niimdesk
    min_width_mm: float = 20
    max_width_mm: float = 50

    @property
    def px_per_mm(self) -> float:
        return self.dpi / 25.4

    @property
    def printhead_mm(self) -> float:
        return self.printhead_pixels / self.px_per_mm


_B1_LABEL_TYPES = (LabelType.WITH_GAPS, LabelType.BLACK_MARK, LabelType.TRANSPARENT)

B1 = PrinterModel("B1", (4096,), 203, 384, _B1_LABEL_TYPES, 1, 5, 3, supported=True)
B1_SE = PrinterModel("B1 SE", (4098,), 203, 384, _B1_LABEL_TYPES, 1, 5, 3, supported=True, max_width_mm=54)
# The B1 Pro uses a different print task (300 dpi, "D110M_V4") that is not implemented.
B1_PRO = PrinterModel("B1 Pro", (4097,), 300, 567, _B1_LABEL_TYPES, 1, 5, 3, supported=False)

MODELS = (B1, B1_SE, B1_PRO)
DEFAULT_MODEL = B1


def model_by_id(model_id: int) -> PrinterModel | None:
    for model in MODELS:
        if model_id in model.model_ids:
            return model
    return None
