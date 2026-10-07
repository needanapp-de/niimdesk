"""Label model (in millimetres) and rendering to a 1-bit image at printer resolution."""

from __future__ import annotations

import base64
import io
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
from typing import Any, ClassVar

import barcode
import qrcode
from barcode.errors import BarcodeError
from PIL import Image, ImageDraw, ImageOps

from niimdesk.protocol.commands import LabelType
from niimdesk.render import qrdata
from niimdesk.render.fonts import DEFAULT_FAMILY, load_font

DEFAULT_DPI = 203
FORMAT_VERSION = 1


@dataclass
class RenderContext:
    dpi: int = DEFAULT_DPI

    @property
    def px_per_mm(self) -> float:
        return self.dpi / 25.4

    def px(self, mm: float) -> int:
        return round(mm * self.px_per_mm)

    def pt_to_px(self, pt: float) -> int:
        return max(1, round(pt * self.dpi / 72))


@dataclass(kw_only=True)
class Element:
    TYPE: ClassVar[str] = ""
    TITLE: ClassVar[str] = ""

    x: float = 2.0
    y: float = 2.0
    width: float = 20.0
    height: float = 10.0

    def box(self, ctx: RenderContext) -> tuple[int, int, int, int]:
        x0, y0 = ctx.px(self.x), ctx.px(self.y)
        return x0, y0, x0 + max(ctx.px(self.width), 1), y0 + max(ctx.px(self.height), 1)

    def summary(self) -> str:
        return self.TITLE

    def validate(self) -> str | None:
        """Error message if the element cannot be rendered, else None."""
        return None

    def draw(self, canvas: Image.Image, ctx: RenderContext) -> None:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.TYPE, **asdict(self)}


def _draw_error_box(canvas: Image.Image, box: tuple[int, int, int, int]) -> None:
    d = ImageDraw.Draw(canvas)
    d.rectangle(box, outline=0, width=2)
    d.line(box, fill=0, width=2)
    d.line((box[0], box[3], box[2], box[1]), fill=0, width=2)


@dataclass(kw_only=True)
class TextElement(Element):
    TYPE: ClassVar[str] = "text"
    TITLE: ClassVar[str] = "Text"

    width: float = 40.0
    height: float = 8.0
    text: str = "Text"
    font: str = DEFAULT_FAMILY
    size_pt: float = 12.0
    bold: bool = False
    align: str = "left"  # left | center | right
    valign: str = "top"  # top | middle | bottom
    wrap: bool = True
    fit: bool = False  # shrink font until the text fits the box

    def summary(self) -> str:
        first = self.text.strip().splitlines()[0] if self.text.strip() else ""
        return f"Text: {first[:30]}"

    def _layout(self, size_px: int, box_w: int) -> tuple[Any, list[str], int]:
        font = load_font(self.font, self.bold, size_px)
        ascent, descent = font.getmetrics()
        lines: list[str] = []
        for paragraph in self.text.split("\n"):
            lines += _wrap(paragraph, font, box_w) if self.wrap else [paragraph]
        return font, lines, ascent + descent

    def draw(self, canvas: Image.Image, ctx: RenderContext) -> None:
        x0, y0, x1, y1 = self.box(ctx)
        box_w, box_h = x1 - x0, y1 - y0
        size_px = ctx.pt_to_px(self.size_pt)

        font, lines, pitch = self._layout(size_px, box_w)
        if self.fit and not self._fits(font, lines, pitch, box_w, box_h):
            # largest size below the configured one that still fits
            best = self._layout(4, box_w)
            lo, hi = 5, size_px - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                candidate = self._layout(mid, box_w)
                if self._fits(*candidate, box_w, box_h):
                    best, lo = candidate, mid + 1
                else:
                    hi = mid - 1
            font, lines, pitch = best

        text_h = pitch * len(lines)
        if self.valign == "middle":
            y = y0 + (box_h - text_h) // 2
        elif self.valign == "bottom":
            y = y1 - text_h
        else:
            y = y0

        d = ImageDraw.Draw(canvas)
        for line in lines:
            w = font.getlength(line)
            if self.align == "center":
                x = x0 + (box_w - w) / 2
            elif self.align == "right":
                x = x1 - w
            else:
                x = x0
            d.text((x, y), line, font=font, fill=0, anchor="la")
            y += pitch

    @staticmethod
    def _fits(font: Any, lines: list[str], pitch: int, box_w: int, box_h: int) -> bool:
        widest = max((font.getlength(line) for line in lines), default=0)
        return widest <= box_w and pitch * len(lines) <= box_h


def _wrap(paragraph: str, font: Any, max_width: int) -> list[str]:
    words = paragraph.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    return lines


@dataclass(kw_only=True)
class QrElement(Element):
    TYPE: ClassVar[str] = "qr"
    TITLE: ClassVar[str] = "QR-Code"

    width: float = 20.0
    height: float = 20.0
    content_type: str = "text"  # key of qrdata.QR_TYPES
    data: str = "https://example.com"  # content of the "text" type
    values: dict[str, str] = field(default_factory=dict)  # fields of all other types
    error_correction: str = "M"  # L | M | Q | H

    def _fields(self) -> dict[str, str]:
        return {"text": self.data} if self.content_type == "text" else self.values

    def payload(self) -> str:
        """The text that is encoded into the QR code."""
        return qrdata.encode(self.content_type, self._fields())

    def summary(self) -> str:
        qr_type = qrdata.QR_TYPES.get(self.content_type)
        if qr_type is None or self.content_type == "text":
            return f"QR: {self.data[:30]}"
        hint = self.values.get(qr_type.summary_key, "")
        return f"QR {qr_type.title}: {hint[:24]}" if hint else f"QR {qr_type.title}"

    def validate(self) -> str | None:
        return qrdata.validate(self.content_type, self._fields())

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        # only keep the fields of the selected type (e.g. no Wi-Fi password in a text QR code)
        qr_type = qrdata.QR_TYPES.get(self.content_type)
        keys = qr_type.keys() if qr_type and self.content_type != "text" else set()
        data["values"] = {k: v for k, v in self.values.items() if k in keys}
        return data

    def effective_error_correction(self) -> str:
        qr_type = qrdata.QR_TYPES.get(self.content_type)
        return (qr_type.error_correction if qr_type else None) or self.error_correction

    def _matrix(self) -> list[list[bool]]:
        levels = {
            "L": qrcode.constants.ERROR_CORRECT_L,
            "M": qrcode.constants.ERROR_CORRECT_M,
            "Q": qrcode.constants.ERROR_CORRECT_Q,
            "H": qrcode.constants.ERROR_CORRECT_H,
        }
        level = levels.get(self.effective_error_correction(), levels["M"])
        qr = qrcode.QRCode(error_correction=level, border=0)
        qr.add_data(self.payload())
        qr.make(fit=True)
        return qr.get_matrix()

    def module_info(self, dpi: int = DEFAULT_DPI) -> tuple[int, float] | None:
        """``(modules per side, module size in mm)`` as printed, or None if invalid."""
        if self.validate():
            return None
        try:
            n = len(self._matrix())
        except ValueError:  # data too long for a QR code
            return None
        ctx = RenderContext(dpi)
        side = min(ctx.px(self.width), ctx.px(self.height))
        return n, max(1, side // n) / ctx.px_per_mm

    def draw(self, canvas: Image.Image, ctx: RenderContext) -> None:
        x0, y0, x1, y1 = self.box(ctx)
        if self.validate():
            _draw_error_box(canvas, (x0, y0, x1, y1))
            return
        matrix = self._matrix()
        n = len(matrix)

        side = min(x1 - x0, y1 - y0)
        module = max(1, side // n)
        ox = x0 + (x1 - x0 - module * n) // 2
        oy = y0 + (y1 - y0 - module * n) // 2
        d = ImageDraw.Draw(canvas)
        for row, cells in enumerate(matrix):
            for col, dark in enumerate(cells):
                if dark:
                    px, py = ox + col * module, oy + row * module
                    d.rectangle((px, py, px + module - 1, py + module - 1), fill=0)


BARCODE_TYPES = {
    "code128": "Code 128",
    "ean13": "EAN-13",
    "ean8": "EAN-8",
    "code39": "Code 39",
}


@dataclass(kw_only=True)
class BarcodeElement(Element):
    TYPE: ClassVar[str] = "barcode"
    TITLE: ClassVar[str] = "Barcode"

    width: float = 40.0
    height: float = 12.0
    data: str = "12345678"
    symbology: str = "code128"
    show_text: bool = True
    text_size_pt: float = 8.0

    def summary(self) -> str:
        return f"{BARCODE_TYPES.get(self.symbology, 'Barcode')}: {self.data[:24]}"

    def _build(self) -> tuple[str, str]:
        code = barcode.get_barcode_class(self.symbology)(self.data, writer=None)
        bits = "".join(code.build())
        text = code.get_fullcode() if self.symbology.startswith("ean") else self.data
        return bits, text

    def validate(self) -> str | None:
        if not self.data:
            return "Barcode ist leer"
        try:
            self._build()
        except (BarcodeError, ValueError, KeyError) as e:
            return f"Ungültiger {BARCODE_TYPES.get(self.symbology, 'Barcode')}: {e}"
        return None

    def draw(self, canvas: Image.Image, ctx: RenderContext) -> None:
        x0, y0, x1, y1 = self.box(ctx)
        if self.validate():
            _draw_error_box(canvas, (x0, y0, x1, y1))
            return
        bits, text = self._build()

        bars_bottom = y1
        font = None
        if self.show_text:
            font = load_font(DEFAULT_FAMILY, False, ctx.pt_to_px(self.text_size_pt))
            ascent, descent = font.getmetrics()
            bars_bottom = y1 - ascent - descent - 1

        module = max(1, (x1 - x0) // len(bits))
        ox = x0 + (x1 - x0 - module * len(bits)) // 2
        d = ImageDraw.Draw(canvas)
        start = None
        for i, bit in enumerate(bits + "0"):
            if bit == "1" and start is None:
                start = i
            elif bit != "1" and start is not None:
                d.rectangle((ox + start * module, y0, ox + i * module - 1, bars_bottom - 1), fill=0)
                start = None

        if font is not None:
            d.text(((x0 + x1) / 2, bars_bottom + 1), text, font=font, fill=0, anchor="ma")


@dataclass(kw_only=True)
class ImageElement(Element):
    TYPE: ClassVar[str] = "image"
    TITLE: ClassVar[str] = "Bild"

    width: float = 20.0
    height: float = 20.0
    name: str = ""
    png_base64: str = ""  # embedded so templates stay self-contained
    dither: bool = True
    threshold: int = 128
    invert: bool = False

    @classmethod
    def from_file(cls, path: str, **kwargs: Any) -> ImageElement:
        with Image.open(path) as img:
            img.load()
            buf = io.BytesIO()
            _flatten(img).save(buf, "PNG")
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return cls(name=name, png_base64=base64.b64encode(buf.getvalue()).decode("ascii"), **kwargs)

    def summary(self) -> str:
        return f"Bild: {self.name or '(leer)'}"

    def validate(self) -> str | None:
        if not self.png_base64:
            return "Kein Bild geladen"
        try:
            _decode_image(self.png_base64)
        except (OSError, ValueError) as e:
            return f"Bild kann nicht gelesen werden: {e}"
        return None

    def source_size(self) -> tuple[int, int] | None:
        try:
            return _decode_image(self.png_base64).size
        except (OSError, ValueError):
            return None

    def draw(self, canvas: Image.Image, ctx: RenderContext) -> None:
        x0, y0, x1, y1 = self.box(ctx)
        if self.validate():
            _draw_error_box(canvas, (x0, y0, x1, y1))
            return
        img = _decode_image(self.png_base64)
        img = ImageOps.contain(img, (x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
        if self.invert:
            img = ImageOps.invert(img)
        if self.dither:
            mono = img.convert("1")  # Floyd-Steinberg
        else:
            mono = img.point(lambda v: 255 if v >= self.threshold else 0, mode="1")
        ox = x0 + (x1 - x0 - img.width) // 2
        oy = y0 + (y1 - y0 - img.height) // 2
        canvas.paste(mono.convert("L"), (ox, oy))


def _flatten(img: Image.Image) -> Image.Image:
    """Grayscale with transparent areas turned white."""
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        img = Image.alpha_composite(background, rgba)
    return img.convert("L")


@lru_cache(maxsize=32)
def _decode_image(png_base64: str) -> Image.Image:
    with Image.open(io.BytesIO(base64.b64decode(png_base64))) as img:
        img.load()
        return _flatten(img)


@dataclass(kw_only=True)
class RectElement(Element):
    TYPE: ClassVar[str] = "rect"
    TITLE: ClassVar[str] = "Rahmen / Linie"

    width: float = 30.0
    height: float = 10.0
    line_mm: float = 0.5
    filled: bool = False

    def summary(self) -> str:
        return "Fläche" if self.filled else "Rahmen"

    def draw(self, canvas: Image.Image, ctx: RenderContext) -> None:
        x0, y0, x1, y1 = self.box(ctx)
        d = ImageDraw.Draw(canvas)
        if self.filled:
            d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
        else:
            d.rectangle((x0, y0, x1 - 1, y1 - 1), outline=0, width=max(1, ctx.px(self.line_mm)))


ELEMENT_TYPES: dict[str, type[Element]] = {
    cls.TYPE: cls for cls in (TextElement, QrElement, BarcodeElement, ImageElement, RectElement)
}


def element_from_dict(data: dict[str, Any]) -> Element:
    cls = ELEMENT_TYPES[data["type"]]
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Label:
    width_mm: float = 50.0
    height_mm: float = 30.0
    density: int = 3
    label_type: int = LabelType.WITH_GAPS
    elements: list[Element] = field(default_factory=list)
    # example values of the table columns ({column} placeholders), shown in the preview without a table
    sample: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "format": "niimdesk-label",
            "version": FORMAT_VERSION,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "density": self.density,
            "label_type": int(self.label_type),
            "elements": [e.to_dict() for e in self.elements],
        }
        if self.sample:
            data["sample"] = dict(self.sample)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Label:
        if data.get("format") != "niimdesk-label":
            raise ValueError("Keine niimdesk-Etikettenvorlage")
        return cls(
            width_mm=float(data.get("width_mm", 50)),
            height_mm=float(data.get("height_mm", 30)),
            density=int(data.get("density", 3)),
            label_type=int(data.get("label_type", LabelType.WITH_GAPS)),
            elements=[element_from_dict(e) for e in data.get("elements", []) if e.get("type") in ELEMENT_TYPES],
            sample={str(k): str(v) for k, v in (data.get("sample") or {}).items()},
        )


def render(label: Label, dpi: int = DEFAULT_DPI) -> Image.Image:
    """Render the full label (mode "1", 0 = black) at ``dpi``."""
    ctx = RenderContext(dpi)
    canvas = Image.new("L", (max(ctx.px(label.width_mm), 8), max(ctx.px(label.height_mm), 1)), 255)
    for element in label.elements:
        element.draw(canvas, ctx)
    return canvas.point(lambda v: 255 if v >= 128 else 0, mode="1")


def printable_area(label_width_px: int, printhead_px: int) -> tuple[int, int]:
    """Horizontal pixel range ``(start, end)`` of the label that the printhead reaches (centered)."""
    if label_width_px <= printhead_px:
        return 0, label_width_px
    start = (label_width_px - printhead_px) // 2
    return start, start + printhead_px


def crop_to_printhead(image: Image.Image, printhead_px: int) -> Image.Image:
    start, end = printable_area(image.width, printhead_px)
    if (start, end) == (0, image.width):
        return image
    return image.crop((start, 0, end, image.height))


def shift(image: Image.Image, dx_px: int, dy_px: int) -> Image.Image:
    """Move the content by (dx, dy) pixels, keeping the size; uncovered areas become white.

    Used to compensate the printer's mechanical label positioning tolerance
    (positive dy = further down the label, positive dx = to the right).
    """
    if dx_px == 0 and dy_px == 0:
        return image
    out = Image.new(image.mode, image.size, 255 if image.mode in ("1", "L") else "white")
    out.paste(image, (dx_px, dy_px))
    return out


def print_image(
    label: Label, dpi: int, printhead_px: int, offset_x_mm: float = 0.0, offset_y_mm: float = 0.0
) -> Image.Image:
    """Exactly what is sent to the printer: rendered, shifted by the calibration offset, cropped."""
    ctx = RenderContext(dpi)
    image = shift(render(label, dpi), ctx.px(offset_x_mm), ctx.px(offset_y_mm))
    return crop_to_printhead(image, printhead_px)


def image_label(path: str, width_mm: float, height_mm: float, dither: bool = True) -> Label:
    """A label that shows one image file as large as possible."""
    element = ImageElement.from_file(path, x=0, y=0, width=width_mm, height=height_mm, dither=dither)
    return Label(width_mm=width_mm, height_mm=height_mm, elements=[element])


def testpage_label(width_mm: float = 50, height_mm: float = 30, printhead_mm: float = 48) -> Label:
    """Test pattern: frame along the printable area, text and a QR code."""
    left = max(0.0, (width_mm - printhead_mm) / 2)
    usable = width_mm - 2 * left
    qr = min(height_mm - 8, usable / 2.6)
    text_w = usable - qr - 7
    return Label(
        width_mm=width_mm,
        height_mm=height_mm,
        elements=[
            RectElement(x=left + 1, y=1, width=usable - 2, height=height_mm - 2, line_mm=0.25),
            TextElement(
                x=left + 3, y=3, width=text_w, height=7, text="niimdesk", size_pt=14, bold=True, fit=True
            ),
            TextElement(
                x=left + 3, y=11, width=text_w, height=height_mm - 14,
                text=f"Testdruck\n{width_mm:g} × {height_mm:g} mm", size_pt=9, fit=True,
            ),
            QrElement(x=left + usable - qr - 3, y=(height_mm - qr) / 2, width=qr, height=qr, data="niimdesk test"),
        ],
    )
