#!/usr/bin/env bash
# Install the built app (dist/niimdesk) for the current user and add a menu entry.
set -euo pipefail
cd "$(dirname "$0")/.."

src="dist/niimdesk"
dest="$HOME/.local/share/niimdesk"
if [ ! -x "$src/niimdesk" ]; then
    echo "Zuerst packaging/build-linux.sh ausführen." >&2
    exit 1
fi

rm -rf "$dest"
mkdir -p "$dest" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp -a "$src/." "$dest/"
ln -sf "$dest/niimdesk-cli" "$HOME/.local/bin/niimdesk"

cat > "$HOME/.local/share/applications/niimdesk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=niimdesk
Comment=Etiketten für den NIIMBOT B1 drucken
Exec=$dest/niimdesk
Icon=$dest/niimdesk.png
Terminal=false
Categories=Office;Utility;
EOF

echo "Installiert nach $dest"
echo "Startmenü: niimdesk   ·   Kommandozeile: niimdesk (in ~/.local/bin)"
