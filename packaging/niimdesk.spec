# PyInstaller spec: builds dist/niimdesk/ with the GUI (niimdesk) and the CLI (niimdesk-cli).
# Usage: pyinstaller --noconfirm --clean packaging/niimdesk.spec   (run on the target OS)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
icon = root / "packaging" / ("niimdesk.ico" if sys.platform == "win32" else "niimdesk.png")

datas = [(str(root / "src" / "niimdesk" / "fonts"), "niimdesk/fonts")]
binaries = []
hiddenimports = collect_submodules("bleak")

if sys.platform == "win32":
    # bleak's WinRT backend is not picked up automatically (bleak issue #1596)
    d, b, h = collect_all("winrt")
    datas += d
    binaries += b
    hiddenimports += h + ["winrt.windows.foundation.collections"]

excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"]


def analysis(script):
    return Analysis(
        [str(root / "packaging" / script)],
        pathex=[str(root / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=excludes,
    )


gui = analysis("niimdesk_gui.py")
cli = analysis("niimdesk_cli.py")

gui_exe = EXE(
    PYZ(gui.pure),
    gui.scripts,
    [],
    exclude_binaries=True,
    name="niimdesk",
    console=False,
    icon=str(icon) if icon.exists() else None,
)
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    [],
    exclude_binaries=True,
    name="niimdesk-cli",
    console=True,
    icon=str(icon) if icon.exists() else None,
)

COLLECT(
    gui_exe,
    gui.binaries,
    gui.datas,
    cli_exe,
    cli.binaries,
    cli.datas,
    name="niimdesk",
)
