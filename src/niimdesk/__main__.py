"""`python -m niimdesk` startet die GUI, `python -m niimdesk <befehl>` die CLI."""

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from niimdesk.cli import main as cli_main

        cli_main()
    else:
        from niimdesk.gui.app import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
