import json
from datetime import datetime

import pytest

from niimdesk.render import merge, qrdata
from niimdesk.render.label import BarcodeElement, ImageElement, Label, QrElement, TextElement, render


def wifi_label() -> Label:
    return Label(
        elements=[
            QrElement(
                content_type="wifi",
                values={
                    "ssid": "{Netzwerkname (SSID)}",
                    "password": "{Passwort}",
                    "security": "{Verschlüsselung}",
                    "hidden": "0",
                },
            ),
            TextElement(text="WLAN: {Netzwerkname (SSID)}"),
        ],
        sample={"Netzwerkname (SSID)": "Gast", "Verschlüsselung": "WPA / WPA2 / WPA3", "unbenutzt": "x"},
    )


def test_placeholders_and_columns_in_order_with_usages():
    assert merge.placeholders("Raum { Nr }, {Haus}") == ["Nr", "Haus"]
    cols = merge.columns(wifi_label())
    assert [c.name for c in cols] == ["Netzwerkname (SSID)", "Passwort", "Verschlüsselung"]
    assert cols[0].usages == ["QR-Code WLAN-Zugang: Netzwerkname (SSID)", "Text"]
    assert cols[2].kind == "choice" and cols[2].allowed()[0] == "WPA / WPA2 / WPA3"
    assert cols[1].kind == "line"


def test_choice_column_only_typed_if_whole_value():
    label = Label(elements=[QrElement(content_type="wifi", values={"ssid": "x", "security": "W{Sec}"})])
    assert merge.columns(label)[0].kind == "line"


def test_fill_label_replaces_and_normalizes():
    record = {"netzwerkname  (ssid)": "Büro", "Passwort": "geheim123", "Verschlüsselung": "wpa2"}
    filled, errors = merge.fill_label(wifi_label(), record)
    assert errors == []
    assert filled.elements[0].payload() == "WIFI:T:WPA;S:Büro;P:geheim123;;"
    assert filled.elements[1].text == "WLAN: Büro"
    # the template itself is untouched
    assert wifi_label().elements[0].values["ssid"] == "{Netzwerkname (SSID)}"


def test_fill_label_reports_missing_columns_and_invalid_values():
    _, errors = merge.fill_label(wifi_label(), {"Netzwerkname (SSID)": "x"})
    assert "Spalte „Passwort“ fehlt in der Tabelle" in errors
    _, errors = merge.fill_label(
        wifi_label(), {"Netzwerkname (SSID)": "x", "Passwort": "kurz", "Verschlüsselung": "WPA"}
    )
    assert errors == ["QR-Code: WPA-Passwörter haben 8 bis 63 Zeichen"]
    _, errors = merge.fill_label(
        wifi_label(), {"Netzwerkname (SSID)": "x", "Passwort": "geheim123", "Verschlüsselung": "Zauber"}
    )
    assert errors[0].startswith("Verschlüsselung: „Zauber“ ist nicht erlaubt")


def test_preview_keeps_unknown_placeholders_without_errors():
    label = wifi_label()
    filled, errors = merge.fill_label(label, label.sample, strict=False)
    assert errors == []
    assert filled.elements[1].text == "WLAN: Gast"
    assert filled.elements[0].values["password"] == "{Passwort}"
    assert render(filled).getbbox() is not None


@pytest.mark.parametrize("kind, cell, expected", [
    ("choice", "Offen, ohne Passwort", "nopass"),
    ("choice", "offen", "nopass"),
    ("choice", "WEP", "WEP"),
    ("choice", "WPA3", "WPA"),
    ("choice", "", "WPA"),
    ("check", "Ja", "1"),
    ("check", "x", "1"),
    ("check", "", "0"),
    ("check", "FALSCH", "0"),
    ("datetime", "24.12.2026 18:30", "2026-12-24T18:30"),
    ("datetime", "24.12.2026", "2026-12-24T00:00"),
    ("datetime", "2026-12-24T18:30:00", "2026-12-24T18:30"),
    ("datetime", "", ""),
])
def test_from_table_value(kind, cell, expected):
    f = {f.kind: f for f in qrdata.QR_TYPES["wifi"].fields + qrdata.QR_TYPES["event"].fields}[kind]
    assert merge.from_table_value(f, cell) == (expected, None)


def test_from_table_value_errors():
    check = qrdata.QR_TYPES["wifi"].fields[3]
    start = qrdata.QR_TYPES["event"].fields[1]
    assert merge.from_table_value(check, "vielleicht")[1]
    assert merge.from_table_value(start, "morgen")[1]


def test_to_table_value_roundtrip():
    for f in qrdata.QR_TYPES["wifi"].fields + qrdata.QR_TYPES["event"].fields:
        for value in {"WPA", "nopass", "1", "0", "2026-10-07T18:00"}:
            if f.kind == "choice" and value not in {v for _, v in f.choices}:
                continue
            if f.kind == "check" and value not in {"0", "1"}:
                continue
            if f.kind == "datetime" and not value.startswith("2026"):
                continue
            assert merge.from_table_value(f, merge.to_table_value(f, value))[0] == value
    assert merge.to_table_value(qrdata.QR_TYPES["event"].fields[1], "2026-10-07T18:00") == "07.10.2026 18:00"


def test_event_from_table():
    label = Label(elements=[QrElement(content_type="event", values={"summary": "{Titel}", "start": "{Beginn}", "end": ""})])
    filled, errors = merge.fill_label(label, {"Titel": "Grillen", "Beginn": "07.10.2026 18:00"})
    assert errors == []
    assert "DTSTART:20261007T180000" in filled.elements[0].payload()


def test_qr_text_barcode_and_mixed_text():
    label = Label(
        elements=[
            QrElement(data="https://example.com/inventar/{Nr}"),
            BarcodeElement(data="{Nr}", symbology="code128"),
            TextElement(text="Inventar {Nr}\n{Raum}"),
            ImageElement(),  # no text slots
        ]
    )
    assert merge.column_names(label) == ["Nr", "Raum"]
    filled, errors = merge.fill_label(label, {"Nr": "A-17", "Raum": "Küche"})
    assert [e for e in errors if "Bild" not in e] == []
    assert filled.elements[0].payload() == "https://example.com/inventar/A-17"
    assert filled.elements[1].data == "A-17"
    assert filled.elements[2].text == "Inventar A-17\nKüche"


def test_unique_column_and_prune_sample():
    label = wifi_label()
    assert merge.unique_column(label, "Passwort") == "Passwort 2"
    assert merge.unique_column(label, "Neu") == "Neu"
    merge.prune_sample(label)
    assert set(label.sample) == {"Netzwerkname (SSID)", "Verschlüsselung"}


@pytest.mark.parametrize("cell, expected", [
    ("", (3, None)), ("2", (2, None)), ("2,0", (2, None)), ("0", (0, None)),
])
def test_copies_of(cell, expected):
    assert merge.copies_of({"anzahl": cell}, 3) == expected


@pytest.mark.parametrize("cell", ["-1", "1,5", "viele", "1000"])
def test_copies_of_invalid(cell):
    copies, error = merge.copies_of({"Anzahl": cell}, 1)
    assert copies == 0 and error


def test_merge_rows_marks_example_and_errors():
    label = wifi_label()
    example = merge.example_values(label)
    rows = [
        {"Netzwerkname (SSID)": "Gast", "Passwort": "", "Verschlüsselung": "WPA / WPA2 / WPA3"},
        {"Netzwerkname (SSID)": "Büro", "Passwort": "geheim123", "Verschlüsselung": "WPA", "Anzahl": "2"},
    ]
    merged = merge.merge_rows(label, rows, [2, 3], default_copies=1, example=example)
    assert merged[0].is_example and not merged[0].ok  # empty WPA password
    assert merged[1].ok and merged[1].copies == 2 and not merged[1].is_example
    assert merged[1].line == 3


def test_sample_is_saved_with_the_template():
    label = wifi_label()
    data = json.loads(json.dumps(label.to_dict()))
    assert Label.from_dict(data).sample == label.sample
    assert "sample" not in Label().to_dict()


def test_datetime_sample_value_is_german():
    f = qrdata.QR_TYPES["event"].fields[1]
    now = datetime(2026, 1, 2, 3, 4).isoformat(timespec="minutes")
    assert merge.to_table_value(f, now) == "02.01.2026 03:04"
