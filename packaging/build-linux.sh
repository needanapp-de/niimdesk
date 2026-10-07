#!/usr/bin/env bash
# Build dist/niimdesk/ and dist/niimdesk-linux-x86_64.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[dev]"

.venv/bin/python -m pytest -q
.venv/bin/python packaging/make_icon.py
.venv/bin/pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/niimdesk.spec
cp packaging/niimdesk.png README.md LICENSE THIRD_PARTY_NOTICES.md dist/niimdesk/

tar -czf dist/niimdesk-linux-x86_64.tar.gz -C dist niimdesk
echo "Fertig: dist/niimdesk/ und dist/niimdesk-linux-x86_64.tar.gz"
echo "Ins Anwendungsmenü eintragen: packaging/install-linux.sh"
