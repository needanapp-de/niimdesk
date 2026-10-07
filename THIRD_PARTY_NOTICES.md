# Third-party notices

## niimbluelib

The NIIMBOT protocol implementation in `src/niimdesk/protocol/` (packet framing, command IDs,
image row encoding, B1 print sequence, response layouts) is ported from niimbluelib
(https://github.com/MultiMote/niimbluelib). The test data in `tests/dumps.py` comes from its test dumps.

```
MIT License

Copyright (c) 2024 MultiMote

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## DejaVu Sans

`src/niimdesk/fonts/DejaVuSans*.ttf`, license in `src/niimdesk/fonts/LICENSE-DejaVu.txt`
(Bitstream Vera license, DejaVu changes are public domain).

## Runtime dependencies

| Package | License |
|---|---|
| bleak | MIT |
| PySide6 / Qt | LGPL-3.0 |
| Pillow | MIT-CMU (HPND) |
| qrcode | BSD |
| python-barcode | MIT |
| openpyxl | MIT |
| et-xmlfile | MIT |
