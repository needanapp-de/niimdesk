# Änderungen

## 0.1.0 – 2026-10-09

Erste Version: Etiketten für den NIIMBOT B1 per Bluetooth am PC gestalten und drucken, ohne die Handy-App.

### Downloads

| System | Datei | So startest du es |
|---|---|---|
| **Windows 10/11** | `niimdesk-0.1.0-windows-x64.zip` | entpacken, im Ordner `niimdesk` die `niimdesk.exe` starten |
| **Linux (x86_64)** | `niimdesk-0.1.0-x86_64.AppImage` | eine einzige Datei: ausführbar machen und starten (siehe unten) |
| Linux, als Ordner | `niimdesk-0.1.0-linux-x86_64.tar.gz` | entpacken, `niimdesk/niimdesk` starten |

**AppImage unter Linux:** nach dem Download ausführbar machen, entweder im Dateimanager unter
*Eigenschaften → Als Programm ausführen* oder im Terminal:

```bash
chmod +x niimdesk-0.1.0-x86_64.AppImage
./niimdesk-0.1.0-x86_64.AppImage
```

Mit einem Befehl dahinter arbeitet dieselbe Datei als Kommandozeilenprogramm, z. B.
`./niimdesk-0.1.0-x86_64.AppImage print vorlage.json`.

**Windows:** Das Programm ist nicht signiert. SmartScreen warnt deshalb beim ersten Start: *Weitere
Informationen → Trotzdem ausführen*. Den B1 **nicht** in den Windows-Bluetooth-Einstellungen koppeln, niimdesk
verbindet sich selbst.

Die Datei `SHA256SUMS.txt` enthält die Prüfsummen aller Downloads.

### Funktionen

- Verbindung zum B1 per Bluetooth LE, ohne Kopplung. Anzeige von Akku, Deckel, Papier und Restetiketten
- Erkennt Original-Etikettenrollen am RFID-Chip und übernimmt Größe und Etikettentyp
- Editor mit Text, QR-Code, Barcode (Code 128, EAN-13/-8, Code 39), Bild und Rahmen
- Vorschau in Druckauflösung (203 dpi, 1 Bit), also genau das, was gedruckt wird
- QR-Inhalte mit passenden Feldern: Kontakt (vCard, MeCard), WLAN, Link, E-Mail, Telefon, SMS, WhatsApp,
  Standort, Kalendertermin, Überweisung (GiroCode)
- Seriendruck aus Excel oder CSV: ein Etikett pro Tabellenzeile. Die passende Tabelle mit allen Spalten
  erstellt niimdesk selbst
- Vorlagen als JSON speichern, Export als PNG
- Kommandozeile für Skripte: `scan`, `info`, `print`, `render`, `table` und mehr

### Bekannte Einschränkungen

- Getestet mit B1 (Firmware 5.20) und Original-Etiketten unter Linux. Unter Windows ist das Programm gebaut
  und geprüft, das Drucken per Bluetooth aber noch nicht mit echter Hardware getestet.
- Nur der B1 wird unterstützt, nicht B1 Pro, D11, D110, B21 usw.
- Etiketten ohne Original-RFID-Chip druckt der B1 eventuell nur sehr blass.

niimdesk ist ein unabhängiges Projekt und kein offizielles Produkt von NIIMBOT.
