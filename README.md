# niimdesk

Desktop-App für den **NIIMBOT B1** Etikettendrucker unter **Linux und Windows**. Die Verbindung läuft per
**Bluetooth LE**. Damit lassen sich Etiketten mit Text, QR-Codes, Barcodes, Bildern und Rahmen gestalten und
drucken, ohne die Handy-App.

- Echte 1-Bit-Vorschau bei 203 dpi, also genau das, was gedruckt wird
- Elemente mit der Maus verschieben und skalieren, Vorlagen als JSON speichern
- Druckerstatus: Akku, Deckel, Papier, verbleibende Etiketten
- **Erkennt die eingelegte Original-Rolle** am RFID-Chip und übernimmt Etikettengröße und Typ automatisch
- Kommandozeile für Skripte und Automatisierung

Getestet mit B1, Firmware 5.20, und Original-Etiketten 50 × 30 mm unter Ubuntu 26.04.

## Installation

### Fertiges Paket

| System  | Datei                             | Start                       |
|---------|-----------------------------------|-----------------------------|
| Linux   | `niimdesk-linux-x86_64.tar.gz`    | entpacken, `niimdesk/niimdesk` |
| Windows | `niimdesk-windows.zip`            | entpacken, `niimdesk\niimdesk.exe` |

Unter Linux trägt `packaging/install-linux.sh` die App ins Anwendungsmenü ein und legt den Befehl `niimdesk`
in `~/.local/bin` an.

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
niimdesk calibrate --offset-x -0.25 --offset-y 0.8
```

| Option | Bedeutung |
|---|---|
| `-a ADRESSE` | Drucker direkt wählen statt suchen |
| `-d 1..5` | Druckdichte |
| `-t gaps\|black\|transparent` | Etikettentyp |
| `--preview datei.png` | gerendertes Bild zusätzlich speichern |
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
```

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1   # -> dist\niimdesk-windows.zip
```

Gebaut wird jeweils auf dem Zielsystem, denn PyInstaller kann nicht für ein anderes Betriebssystem bauen.
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
  render/     label.py (Etikettenmodell in mm → 1-Bit-Bild), fonts.py
  gui/        PySide6-Oberfläche, worker.py (Bluetooth in eigenem Thread)
  cli.py, config.py, models.py
```

Die Tests prüfen Pakete und Antworten gegen echte B1-Mitschnitte und simulieren einen kompletten Druckablauf.
Ein Drucker ist dafür nicht nötig.

## Lizenz

MIT, siehe [LICENSE](LICENSE).

- **Druckerprotokoll:** basiert auf [niimbluelib](https://github.com/MultiMote/niimbluelib) von MultiMote (MIT).
- **Schrift:** DejaVu Sans (Bitstream-Vera-Lizenz).
- Details in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
