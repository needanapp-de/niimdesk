"""QR code content types (contact, Wi-Fi, payment, ...) with their input fields and encoders.

Formats:
- vCard 3.0 (RFC 2426), MeCard (NTT Docomo), Wi-Fi (ZXing "WIFI:" scheme),
- mailto/tel/geo URIs, SMSTO, wa.me links, iCalendar VEVENT,
- EPC069-12 "GiroCode" (SEPA credit transfer, version 002).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "line"  # line | multiline | password | choice | check | datetime
    placeholder: str = ""
    choices: tuple[tuple[str, str], ...] = ()  # (label, value)
    default: str = ""


@dataclass(frozen=True)
class QrType:
    key: str
    title: str
    fields: tuple[Field, ...]
    encode: Callable[[dict[str, str]], str]
    validate: Callable[[dict[str, str]], str | None] = lambda _f: None
    summary_key: str = ""
    error_correction: str | None = None  # forced level, e.g. "M" for GiroCode
    notes: str = ""

    def values(self, fields: dict[str, str]) -> dict[str, str]:
        """Field values with defaults filled in and surrounding whitespace removed (except multi-line text)."""
        out = {}
        for f in self.fields:
            value = fields.get(f.key, f.default)
            out[f.key] = value if f.kind == "multiline" else value.strip()
        return out

    def keys(self) -> set[str]:
        return {f.key for f in self.fields}


# --- helpers ---------------------------------------------------------------

def _escape(value: str, specials: str) -> str:
    out = value.replace("\\", "\\\\")
    for ch in specials:
        out = out.replace(ch, "\\" + ch)
    return out


def _vcard_escape(value: str) -> str:
    return _escape(value, ",;").replace("\r\n", "\\n").replace("\n", "\\n")


def _ical_escape(value: str) -> str:
    return _vcard_escape(value)


def _required(fields: dict[str, str], *keys_and_labels: tuple[str, str]) -> str | None:
    missing = [label for key, label in keys_and_labels if not fields.get(key, "").strip()]
    return f"Bitte ausfüllen: {', '.join(missing)}" if missing else None


def _phone(value: str) -> str:
    """Keep digits and a leading +."""
    value = value.strip()
    digits = re.sub(r"[^\d]", "", value)
    return ("+" + digits) if value.startswith("+") else digits


# --- encoders --------------------------------------------------------------

def _text(f: dict[str, str]) -> str:
    return f["text"]


def _url(f: dict[str, str]) -> str:
    url = f["url"]
    if url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        url = "https://" + url
    return url


def _vcard(f: dict[str, str]) -> str:
    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    first, last = f["first_name"], f["last_name"]
    lines.append(f"N:{_vcard_escape(last)};{_vcard_escape(first)};;;")
    full = " ".join(p for p in (first, last) if p) or f["org"]
    lines.append(f"FN:{_vcard_escape(full)}")
    if f["org"]:
        lines.append(f"ORG:{_vcard_escape(f['org'])}")
    if f["title"]:
        lines.append(f"TITLE:{_vcard_escape(f['title'])}")
    if f["phone"]:
        lines.append(f"TEL;TYPE=WORK,VOICE:{_phone(f['phone'])}")
    if f["mobile"]:
        lines.append(f"TEL;TYPE=CELL:{_phone(f['mobile'])}")
    if f["email"]:
        lines.append(f"EMAIL;TYPE=INTERNET:{f['email']}")
    if f["website"]:
        lines.append(f"URL:{_url({'url': f['website']})}")
    if any(f[k] for k in ("street", "zip", "city", "country")):
        adr = ";".join(_vcard_escape(f[k]) for k in ("street", "city", "region", "zip", "country"))
        lines.append(f"ADR;TYPE=WORK:;;{adr}")
    if f["note"]:
        lines.append(f"NOTE:{_vcard_escape(f['note'])}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)


def _mecard(f: dict[str, str]) -> str:
    esc = lambda v: _escape(v, ";,:\"")  # noqa: E731
    name = ",".join(esc(p) for p in (f["last_name"], f["first_name"]) if p)
    parts = [f"N:{name}"]
    for key, tag in (("phone", "TEL"), ("email", "EMAIL"), ("website", "URL"), ("address", "ADR"), ("note", "NOTE")):
        if f[key]:
            value = _phone(f[key]) if key == "phone" else f[key]
            parts.append(f"{tag}:{esc(value)}")
    return "MECARD:" + ";".join(parts) + ";;"


def _wifi(f: dict[str, str]) -> str:
    esc = lambda v: _escape(v, ";,:\"")  # noqa: E731
    security = f["security"]
    parts = [f"T:{security}", f"S:{esc(f['ssid'])}"]
    if security != "nopass":
        parts.append(f"P:{esc(f['password'])}")
    if f["hidden"] == "1":
        parts.append("H:true")
    return "WIFI:" + ";".join(parts) + ";;"


def _wifi_validate(f: dict[str, str]) -> str | None:
    if not f["ssid"]:
        return "Bitte den Netzwerknamen (SSID) eingeben"
    if f["security"] == "WPA" and not 8 <= len(f["password"]) <= 63:
        return "WPA-Passwörter haben 8 bis 63 Zeichen"
    if f["security"] == "WEP" and not f["password"]:
        return "Bitte das WEP-Passwort eingeben"
    return None


def _email(f: dict[str, str]) -> str:
    query = []
    if f["subject"]:
        query.append("subject=" + quote(f["subject"]))
    if f["body"]:
        query.append("body=" + quote(f["body"]))
    return f"mailto:{f['address']}" + ("?" + "&".join(query) if query else "")


def _email_validate(f: dict[str, str]) -> str | None:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["address"]):
        return "Bitte eine gültige E-Mail-Adresse eingeben"
    return None


def _tel(f: dict[str, str]) -> str:
    return "tel:" + _phone(f["number"])


def _sms(f: dict[str, str]) -> str:
    return f"SMSTO:{_phone(f['number'])}:{f['message']}"


def _whatsapp(f: dict[str, str]) -> str:
    digits = re.sub(r"\D", "", f["number"])
    if digits.startswith("00"):
        digits = digits[2:]
    url = f"https://wa.me/{digits}"
    return url + ("?text=" + quote(f["message"]) if f["message"] else "")


def _number_validate(f: dict[str, str]) -> str | None:
    if len(re.sub(r"\D", "", f["number"])) < 3:
        return "Bitte eine Telefonnummer eingeben"
    return None


def _whatsapp_validate(f: dict[str, str]) -> str | None:
    if not f["number"].strip().startswith(("+", "00")):
        return "Nummer international eingeben, z. B. +49 170 1234567"
    return _number_validate(f)


def _coordinate(value: str) -> float:
    return float(value.replace(",", "."))


def _geo(f: dict[str, str]) -> str:
    def fmt(v: float) -> str:
        return f"{v:.6f}".rstrip("0").rstrip(".")

    return f"geo:{fmt(_coordinate(f['lat']))},{fmt(_coordinate(f['lon']))}"


def _geo_validate(f: dict[str, str]) -> str | None:
    try:
        lat, lon = _coordinate(f["lat"]), _coordinate(f["lon"])
    except ValueError:
        return "Breiten- und Längengrad als Zahl eingeben, z. B. 52.520008 und 13.404954"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "Koordinaten außerhalb des gültigen Bereichs"
    return None


def _ical_time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%S")


def _event(f: dict[str, str]) -> str:
    lines = ["BEGIN:VEVENT", f"SUMMARY:{_ical_escape(f['summary'])}", f"DTSTART:{_ical_time(f['start'])}"]
    if f["end"]:
        lines.append(f"DTEND:{_ical_time(f['end'])}")
    if f["location"]:
        lines.append(f"LOCATION:{_ical_escape(f['location'])}")
    if f["description"]:
        lines.append(f"DESCRIPTION:{_ical_escape(f['description'])}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def _event_validate(f: dict[str, str]) -> str | None:
    if error := _required(f, ("summary", "Titel"), ("start", "Beginn")):
        return error
    try:
        start = datetime.fromisoformat(f["start"])
        if f["end"] and datetime.fromisoformat(f["end"]) < start:
            return "Das Ende liegt vor dem Beginn"
    except ValueError:
        return "Ungültiges Datum"
    return None


def iban_valid(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def _amount(value: str) -> float | None:
    value = value.replace("€", "").replace(" ", "")
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    return float(value)


def _girocode(f: dict[str, str]) -> str:
    amount = _amount(f["amount"])
    return "\n".join(
        [
            "BCD",
            "002",
            "1",  # UTF-8
            "SCT",
            f["bic"].replace(" ", "").upper(),
            f["name"],
            f["iban"].replace(" ", "").upper(),
            f"EUR{amount:.2f}" if amount else "",
            "",  # purpose code
            "",  # structured reference
            f["reference"],
        ]
    ).rstrip("\n")


def _girocode_validate(f: dict[str, str]) -> str | None:
    if error := _required(f, ("name", "Empfänger"), ("iban", "IBAN")):
        return error
    if len(f["name"]) > 70:
        return "Empfängername höchstens 70 Zeichen"
    if not iban_valid(f["iban"]):
        return "IBAN ist ungültig (Prüfsumme stimmt nicht)"
    if f["bic"] and not re.fullmatch(r"[A-Za-z]{6}[A-Za-z0-9]{2}([A-Za-z0-9]{3})?", f["bic"].replace(" ", "")):
        return "BIC ist ungültig"
    try:
        amount = _amount(f["amount"])
    except ValueError:
        return "Betrag als Zahl eingeben, z. B. 12,50"
    if amount is not None and not 0.01 <= amount <= 999_999_999.99:
        return "Betrag zwischen 0,01 und 999.999.999,99 €"
    if len(f["reference"]) > 140:
        return "Verwendungszweck höchstens 140 Zeichen"
    return None


# --- registry --------------------------------------------------------------

QR_TYPES: dict[str, QrType] = {
    t.key: t
    for t in (
        QrType(
            "text", "Text",
            (Field("text", "Text", "multiline", "Beliebiger Text"),),
            _text, lambda f: None if f["text"] else "QR-Code ist leer", "text",
        ),
        QrType(
            "url", "Link / Webseite",
            (Field("url", "Adresse", placeholder="https://example.com"),),
            _url, lambda f: _required(f, ("url", "Adresse")), "url",
        ),
        QrType(
            "vcard", "Kontakt (vCard)",
            (
                Field("first_name", "Vorname"),
                Field("last_name", "Nachname"),
                Field("org", "Firma"),
                Field("title", "Position"),
                Field("phone", "Telefon", placeholder="+49 30 1234567"),
                Field("mobile", "Mobil", placeholder="+49 170 1234567"),
                Field("email", "E-Mail"),
                Field("website", "Webseite"),
                Field("street", "Straße"),
                Field("zip", "PLZ"),
                Field("city", "Ort"),
                Field("region", "Bundesland"),
                Field("country", "Land"),
                Field("note", "Notiz", "multiline"),
            ),
            _vcard,
            lambda f: None if any(f[k] for k in ("first_name", "last_name", "org")) else "Bitte Name oder Firma eingeben",
            "last_name",
            notes="Wird beim Scannen als Kontakt gespeichert. Viele Felder machen den Code größer.",
        ),
        QrType(
            "mecard", "Kontakt kompakt (MeCard)",
            (
                Field("first_name", "Vorname"),
                Field("last_name", "Nachname"),
                Field("phone", "Telefon"),
                Field("email", "E-Mail"),
                Field("website", "Webseite"),
                Field("address", "Adresse", placeholder="Straße, PLZ Ort"),
                Field("note", "Notiz"),
            ),
            _mecard,
            lambda f: None if (f["first_name"] or f["last_name"]) else "Bitte einen Namen eingeben",
            "last_name",
            notes="Kürzer als vCard, dadurch gröbere Punkte und auf kleinen Etiketten besser lesbar.",
        ),
        QrType(
            "wifi", "WLAN-Zugang",
            (
                Field("ssid", "Netzwerkname (SSID)"),
                Field("password", "Passwort", "password"),
                Field(
                    "security", "Verschlüsselung", "choice",
                    choices=(("WPA / WPA2 / WPA3", "WPA"), ("WEP (veraltet)", "WEP"), ("Offen, ohne Passwort", "nopass")),
                    default="WPA",
                ),
                Field("hidden", "Verstecktes Netzwerk", "check", default="0"),
            ),
            _wifi, _wifi_validate, "ssid",
            notes="Handy-Kamera auf den Code halten, um sich direkt mit dem WLAN zu verbinden.",
        ),
        QrType(
            "email", "E-Mail",
            (
                Field("address", "An", placeholder="name@example.com"),
                Field("subject", "Betreff"),
                Field("body", "Text", "multiline"),
            ),
            _email, _email_validate, "address",
        ),
        QrType(
            "tel", "Telefonnummer",
            (Field("number", "Nummer", placeholder="+49 30 1234567"),),
            _tel, _number_validate, "number",
        ),
        QrType(
            "sms", "SMS",
            (Field("number", "Nummer", placeholder="+49 170 1234567"), Field("message", "Nachricht", "multiline")),
            _sms, _number_validate, "number",
        ),
        QrType(
            "whatsapp", "WhatsApp-Nachricht",
            (Field("number", "Nummer", placeholder="+49 170 1234567"), Field("message", "Nachricht", "multiline")),
            _whatsapp, _whatsapp_validate, "number",
        ),
        QrType(
            "geo", "Standort",
            (Field("lat", "Breitengrad", placeholder="52.520008"), Field("lon", "Längengrad", placeholder="13.404954")),
            _geo, _geo_validate, "lat",
            notes="Koordinaten z. B. aus Google Maps: Rechtsklick auf den Ort.",
        ),
        QrType(
            "event", "Kalendertermin",
            (
                Field("summary", "Titel"),
                Field("start", "Beginn", "datetime"),
                Field("end", "Ende", "datetime"),
                Field("location", "Ort"),
                Field("description", "Beschreibung", "multiline"),
            ),
            _event, _event_validate, "summary",
        ),
        QrType(
            "girocode", "Überweisung (GiroCode)",
            (
                Field("name", "Empfänger"),
                Field("iban", "IBAN", placeholder="DE89 3704 0044 0532 0130 00"),
                Field("bic", "BIC (optional)"),
                Field("amount", "Betrag in €", placeholder="optional, z. B. 12,50"),
                Field("reference", "Verwendungszweck"),
            ),
            _girocode, _girocode_validate, "name",
            error_correction="M",
            notes="Banking-Apps füllen damit eine SEPA-Überweisung aus (EPC-QR-Code).",
        ),
    )
}


def encode(content_type: str, fields: dict[str, str]) -> str:
    qr_type = QR_TYPES[content_type]
    return qr_type.encode(qr_type.values(fields))


def validate(content_type: str, fields: dict[str, str]) -> str | None:
    qr_type = QR_TYPES.get(content_type)
    if qr_type is None:
        return f"Unbekannter QR-Inhalt „{content_type}“"
    values = qr_type.values(fields)
    try:
        if error := qr_type.validate(values):
            return error
        qr_type.encode(values)
    except (ValueError, KeyError) as e:
        return f"Ungültige Eingabe: {e}"
    return None


