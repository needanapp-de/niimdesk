#!/usr/bin/env bash
# Pack the PyInstaller build (dist/niimdesk) into one executable file: dist/niimdesk-<version>-x86_64.AppImage
# Usage: packaging/build-appimage.sh [version]   (run packaging/build-linux.sh first)
set -euo pipefail
cd "$(dirname "$0")/.."

# tagged releases, verified by checksum (same values as the asset digests on GitHub)
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

version="${1:-$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/niimdesk/__init__.py)}"
tools="build/appimage-tools"
appdir="build/AppDir"
out="dist/niimdesk-${version}-x86_64.AppImage"

if [ ! -x dist/niimdesk/niimdesk ] || [ ! -f packaging/niimdesk.png ]; then
    echo "Zuerst packaging/build-linux.sh ausführen." >&2
    exit 1
fi

fetch() {  # url sha256 target
    if [ -f "$3" ] && echo "$2  $3" | sha256sum --check --status; then
        return
    fi
    curl -fsSL -o "$3.part" "$1"
    if ! echo "$2  $3.part" | sha256sum --check --status; then
        echo "Prüfsumme von $1 stimmt nicht" >&2
        rm -f "$3.part"
        exit 1
    fi
    mv "$3.part" "$3"
}
mkdir -p "$tools"
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" "$tools/appimagetool"
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" "$tools/runtime"
chmod +x "$tools/appimagetool"

rm -rf "$appdir"
mkdir -p "$appdir/usr/lib"
cp -a dist/niimdesk "$appdir/usr/lib/niimdesk"
cp packaging/niimdesk.png "$appdir/niimdesk.png"
ln -s niimdesk.png "$appdir/.DirIcon"

cat > "$appdir/niimdesk.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=niimdesk
Comment=Etiketten für den NIIMBOT B1 per Bluetooth drucken
Exec=niimdesk
Icon=niimdesk
Terminal=false
Categories=Office;
Keywords=NIIMBOT;B1;Etiketten;Label;Drucker;
EOF

cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
# Without arguments the app starts; with a subcommand the command line tool runs,
# e.g. "./niimdesk-x86_64.AppImage print vorlage.json"
here="$(dirname "$(readlink -f "$0")")"
case "${1:-}" in
    scan|info|print|testpage|render|table|calibrate|diagnose|-h|--help|--version|-v|-vv|--verbose)
        exec "$here/usr/lib/niimdesk/niimdesk-cli" "$@" ;;
esac
exec "$here/usr/lib/niimdesk/niimdesk" "$@"
EOF
chmod +x "$appdir/AppRun"

rm -f "$out"
# extract-and-run: works without FUSE (e.g. in CI containers)
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$tools/appimagetool" --no-appstream \
    --runtime-file "$tools/runtime" "$appdir" "$out"
echo "Fertig: $out"
