# niimdesk

Desktop-App für den **NIIMBOT B1** Etikettendrucker unter **Linux und Windows**. Die Verbindung läuft per
**Bluetooth LE**. Damit lassen sich Etiketten mit Text, QR-Codes, Barcodes, Bildern und Rahmen gestalten und
drucken, ohne die Handy-App.

- Echte 1-Bit-Vorschau bei 203 dpi, also genau das, was gedruckt wird
- Elemente mit der Maus verschieben und skalieren, Vorlagen als JSON speichern
- Druckerstatus: Akku, Deckel, Papier, verbleibende Etiketten
- **Erkennt die eingelegte Original-Rolle** am RFID-Chip und übernimmt Etikettengröße und Typ automatisch
- **Seriendruck aus Excel:** ein Etikett pro Tabellenzeile, die passende Tabelle erstellt niimdesk selbst
- Kommandozeile für Skripte und Automatisierung

Getestet mit B1, Firmware 5.20, und Original-Etiketten 50 × 30 mm unter Ubuntu 26.04.

> Inoffizielles Projekt, nicht mit NIIMBOT verbunden (siehe [Lizenz](#lizenz)).

## Installation

### Fertiges Paket

Downloads unter **[Releases](https://github.com/needanapp-de/niimdesk/releases/latest)**:

| System  | Datei                                  | Start                                     |
|---------|----------------------------------------|-------------------------------------------|
| Windows | `niimdesk-<version>-windows-x64.zip`   | entpacken, `niimdesk\niimdesk.exe`        |
| Linux   | `niimdesk-<version>-x86_64.AppImage`   | ausführbar machen (`chmod +x …`), starten |
| Linux   | `niimdesk-<version>-linux-x86_64.tar.gz` | entpacken, `niimdesk/niimdesk`          |

Das AppImage ist eine einzige Datei ohne Installation. Mit einem Befehl dahinter arbeitet es als
Kommandozeilenprogramm, z. B. `./niimdesk-<version>-x86_64.AppImage info`.

Aus dem `.tar.gz` trägt `packaging/install-linux.sh` die App ins Anwendungsmenü ein und legt den Befehl
`niimdesk` in `~/.local/bin` an.

### Aus dem Quellcode (Python ≥ 3.11)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/niimdesk-gui
```

Unter Windows heißen die Pfade `.venv\Scripts\...`.

## Drucker verbinden

1. B1 einschalten.
2. **Ist er mit der Handy-App verbunden, dort trennen**, sonst ist er für den PC unsichtbar.
3. In niimdesk auf **„Drucker verbinden …“** klicken und den Eintrag `B1-…` wählen.

Ein Pairing ist nicht nötig. **Unter Windows den B1 nicht in den Bluetooth-Einstellungen koppeln.** Das führt
zu ständigen Verbindungsabbrüchen. Falls schon gekoppelt: dort entfernen.

Ab dann verbindet sich niimdesk beim Start automatisch mit diesem Drucker.

## Bedienung

- **Links:** Etikett (Größe, Typ, Druckdichte 1–5, Standard 3), Elemente hinzufügen, Kopien, Drucken.
- **Mitte:** Vorschau.
  - Elemente anklicken und ziehen.
  - Mit dem blauen Eckpunkt die Größe ändern.
  - Pfeiltasten verschieben um 0,5 mm (mit Shift um 0,1 mm), Entf löscht.
  - Die schraffierten Streifen links und rechts erreicht der 48-mm-Druckkopf nicht.
- **Rechts:** Eigenschaften des gewählten Elements.
  - Text: Schrift, Größe, fett, Ausrichtung, „verkleinern bis es passt“.
  - QR-Code: Inhaltstyp wählen und die passenden Felder ausfüllen.
    - Kontakte: vCard, kompakte MeCard
    - Verbindungen: WLAN-Zugang, Link, E-Mail, Telefon, SMS, WhatsApp
    - Sonstiges: Standort, Kalendertermin, Überweisung (GiroCode/EPC), freier Text
    - Darunter stehen der kodierte Inhalt und eine Warnung, wenn die QR-Punkte zu klein zum Scannen werden.
  - Barcode: Code 128, EAN-13, EAN-8, Code 39.
  - Bild: gerastert oder mit Schwellwert.
- **Datei-Menü:** Vorlagen (`.json`) speichern und öffnen. Bilder werden in die Vorlage eingebettet. Export als PNG.

### Seriendruck aus einer Excel-Tabelle

Ein Etikett pro Tabellenzeile, z. B. WLAN-Zugänge, Inventarnummern oder Namensschilder.

1. **Felder an die Tabelle binden.**
   - QR-Code: neben einem Feld auf das Tabellen-Symbol klicken oder „Alle Felder aus Tabelle“ wählen. Das
     Feld zeigt dann `{Spaltenname}`.
   - Text und Barcode: „Tabellenspalte einfügen“ oder `{Spaltenname}` direkt eintippen. Gemischt geht auch,
     z. B. `Raum {Raum}` oder `https://example.com/inventar/{Nr}`.
   - Der bisherige Wert wird zum Beispielwert. Die Vorschau zeigt ihn weiter an.
2. **Seriendruck → Tabelle erstellen …** speichert eine Excel-Datei (`.xlsx`, wahlweise CSV) mit:
   - einer Spalte pro Feld, Hinweise als Kommentar an der Überschrift,
   - Zeile 2 als Beispiel,
   - Auswahllisten für Felder mit festen Werten, z. B. die WLAN-Verschlüsselung,
   - der Spalte „Anzahl“: wie oft die Zeile gedruckt wird, leer = Kopien aus niimdesk, 0 = überspringen.
3. Die Tabelle in Excel oder LibreOffice ausfüllen und speichern.
4. **Seriendruck → Tabelle öffnen …** zeigt die Zeilen unter der Vorschau.
   - Ein Klick auf eine Zeile zeigt ihr Etikett in der Vorschau.
   - Fehlerhafte Zeilen, z. B. mit zu kurzem WLAN-Passwort oder ungültiger IBAN, sind rot markiert und werden
     nicht gedruckt.
   - Die unveränderte Beispielzeile ist abgewählt.
   - Speichern in Excel lädt die Tabelle automatisch neu.
5. **„N Etiketten drucken“** druckt die angehakten Zeilen nacheinander. Bricht der Druck ab, z. B. weil das
   Papier leer ist, sind die schon gedruckten Zeilen markiert. Erneutes Drucken macht mit den übrigen weiter.

**Gut zu wissen:**
- Eine von niimdesk erstellte Tabelle enthält ihr Etikett. Sie zu öffnen genügt, auch auf einem anderen
  Rechner.
- Eigene Tabellen gehen auch, wenn die Überschriften in der ersten Zeile zu den `{Spalten}` passen.
  Groß- und Kleinschreibung spielen keine Rolle.
- Formate: `.xlsx` und `.csv` (Semikolon oder Komma). `.xls`- und `.ods`-Dateien vorher als `.xlsx` speichern.
- Datum und Uhrzeit als `TT.MM.JJJJ HH:MM`, Ja/Nein-Felder als `ja`/`nein` (auch `x`, `1`, `0`).
- Echte WLAN-Passwörter landen nicht in der Beispielzeile.

### Etikettenrolle

Original-Rollen haben einen RFID-Chip. Der B1 meldet darüber die Rollennummer, den Etikettentyp und wie viele
Etiketten noch übrig sind, **nicht aber die Größe**.

- **Neue Rolle:** niimdesk fragt einmal nach der Größe und merkt sich die Zuordnung.
- **Bekannte Rolle:** niimdesk zeigt **„✓ Etikettenrolle erkannt“**, übernimmt Größe und Typ und sperrt die
  Felder.
- **Falsche Zuordnung:** über „Andere Größe zuordnen …“ korrigieren.
- **Ohne Original-Rolle:** Größe und Typ selbst einstellen.

### Druckversatz

Unter **Drucker → Druckversatz …** lässt sich der Druck verschieben. Das ist nur nötig, wenn er bei *allen*
Etiketten deutlich (über 0,5 mm) in dieselbe Richtung verrutscht ist.

Kleinere Abweichungen schwanken von Etikett zu Etikett, weil die Rolle seitlich etwas Spiel hat. Sie lassen sich
nicht wegkalibrieren. Wichtige Inhalte deshalb mindestens 1,5 mm vom Etikettenrand entfernt halten.

Die Werte gelten für App und CLI und liegen in `~/.config/niimdesk/config.json` (Windows:
`%APPDATA%\niimdesk\config.json`).

## Kommandozeile

```bash
niimdesk scan                              # Drucker in der Nähe suchen
niimdesk info                              # Modell, Firmware, Akku, Deckel, Papier, Etiketten
niimdesk testpage --size 50x30             # Testetikett
niimdesk print logo.png --size 40x30 -c 3  # Bild drucken (3 Kopien)
niimdesk print vorlage.json                # Vorlage aus der App drucken
niimdesk render vorlage.json -o test.png   # nur rendern, ohne Drucker
niimdesk table vorlage.json                # Excel-Tabelle für den Seriendruck erstellen
niimdesk print vorlage-tabelle.xlsx        # Seriendruck: ein Etikett pro Tabellenzeile
niimdesk print vorlage.json --data liste.csv --rows 3-10
niimdesk render vorlage-tabelle.xlsx -o e.png   # e-003.png, e-004.png … ohne Drucker
niimdesk calibrate --offset-x -0.25 --offset-y 0.8
```

| Option | Bedeutung |
|---|---|
| `-a ADRESSE` | Drucker direkt wählen statt suchen |
| `-d 1..5` | Druckdichte |
| `-t gaps\|black\|transparent` | Etikettentyp |
| `--preview datei.png` | gerendertes Bild zusätzlich speichern |
| `--data TABELLE` | Seriendruck aus `.xlsx`/`.csv` (bei Tabellen aus niimdesk nicht nötig) |
| `--rows 3-10,12` | nur diese Tabellenzeilen |
| `--skip-errors` | fehlerhafte Zeilen auslassen statt abzubrechen |
| `-v` / `-vv` | Log bzw. alle Pakete ausgeben |

Im gepackten Programm heißt der Befehl `niimdesk-cli`.

## Bekannte Grenzen

- **Etiketten ohne Original-RFID-Chip** druckt der B1 eventuell kaum sichtbar (sehr geringe Dichte).
  niimdesk warnt in diesem Fall.
- **B1 Pro** (300 dpi) nutzt ein anderes Druckprotokoll und wird noch nicht unterstützt.
- **Andere NIIMBOT-Modelle** (D11, D110, B21 …) werden noch nicht unterstützt.
- **Rot/schwarze Etiketten** werden noch nicht unterstützt.
- **Nur ein Gerät gleichzeitig:** Solange niimdesk verbunden ist, kommt die Handy-App nicht an den Drucker
  und umgekehrt.

## Selbst bauen

```bash
packaging/build-linux.sh        # -> dist/niimdesk/, dist/niimdesk-linux-x86_64.tar.gz
packaging/build-appimage.sh     # danach: -> dist/niimdesk-<version>-x86_64.AppImage
```

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1   # -> dist\niimdesk-windows.zip
```

Gebaut wird jeweils auf dem Zielsystem, denn PyInstaller kann nicht für ein anderes Betriebssystem bauen.

**Release veröffentlichen:** Version in `src/niimdesk/__init__.py` und `pyproject.toml` erhöhen, einen
Abschnitt in [CHANGELOG.md](CHANGELOG.md) anlegen, dann ein Tag `v<version>` pushen. GitHub Actions baut
Windows und Linux, erzeugt die Prüfsummen und veröffentlicht das Release mit dem Text aus dem Changelog.
Unter Windows braucht es Python ≥ 3.11 von python.org (mit dem `py`-Launcher).

## Entwicklung

```bash
.venv/bin/python -m pytest
```

Projektaufbau:

```
src/niimdesk/
  protocol/   packet.py (Rahmenformat), commands.py, encoder.py (Bild → Zeilenpakete),
              parsers.py, client.py (Verbindung, Status, Druckablauf)
  transport/  ble.py (bleak: Linux BlueZ, Windows WinRT)
  render/     label.py (Etikettenmodell in mm → 1-Bit-Bild), fonts.py, qrdata.py (QR-Inhaltstypen),
              merge.py ({Spalte}-Platzhalter für den Seriendruck)
  gui/        PySide6-Oberfläche, worker.py (Bluetooth in eigenem Thread), merge_panel.py (Tabellenansicht)
  table.py    Excel/CSV lesen und Tabellenvorlagen schreiben
  cli.py, config.py, models.py
```

Die Tests prüfen Pakete und Antworten gegen echte B1-Mitschnitte und simulieren einen kompletten Druckablauf.
Ein Drucker ist dafür nicht nötig.

## Lizenz

MIT, siehe [LICENSE](LICENSE).

niimdesk ist ein unabhängiges Projekt und kein offizielles Produkt von NIIMBOT. Es steht in keiner Verbindung
zum Hersteller und wird von ihm weder unterstützt noch geprüft. „NIIMBOT“ ist eine Marke ihres Inhabers und
wird hier nur verwendet, um die unterstützten Geräte zu benennen. Nutzung auf eigenes Risiko.

- **Druckerprotokoll:** basiert auf [niimbluelib](https://github.com/MultiMote/niimbluelib) von MultiMote (MIT).
- **Schrift:** DejaVu Sans (Bitstream-Vera-Lizenz).
- Details in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
