import json

import pytest

from niimdesk.render import qrdata
from niimdesk.render.label import Label, QrElement, element_from_dict, render


def test_every_type_validates_and_encodes_its_example():
    examples = {
        "text": {"text": "Hallo"},
        "url": {"url": "example.com"},
        "vcard": {"first_name": "Erika", "last_name": "Mustermann"},
        "mecard": {"first_name": "Erika", "last_name": "Mustermann"},
        "wifi": {"ssid": "Heimnetz", "password": "geheim123"},
        "email": {"address": "erika@example.com"},
        "tel": {"number": "+49 30 1234567"},
        "sms": {"number": "+49 170 1234567"},
        "whatsapp": {"number": "+49 170 1234567"},
        "geo": {"lat": "52.520008", "lon": "13.404954"},
        "event": {"summary": "Treffen", "start": "2026-10-07T18:00"},
        "girocode": {"name": "Erika Mustermann", "iban": "DE89 3704 0044 0532 0130 00"},
    }
    assert set(examples) == set(qrdata.QR_TYPES)
    for key, fields in examples.items():
        assert qrdata.validate(key, fields) is None, key
        assert qrdata.encode(key, fields), key


def test_url_gets_scheme():
    assert qrdata.encode("url", {"url": "example.com/x"}) == "https://example.com/x"
    assert qrdata.encode("url", {"url": "http://a.b"}) == "http://a.b"


def test_vcard_escapes_and_orders_address():
    card = qrdata.encode(
        "vcard",
        {
            "first_name": "Erika", "last_name": "Muster;mann", "org": "A, B & C",
            "mobile": "+49 (170) 123-45", "street": "Hauptstr. 1", "zip": "10115", "city": "Berlin",
            "country": "Deutschland", "note": "Zeile 1\nZeile 2",
        },
    )
    lines = card.split("\r\n")
    assert lines[0] == "BEGIN:VCARD" and lines[-1] == "END:VCARD"
    assert "N:Muster\\;mann;Erika;;;" in lines
    assert "ORG:A\\, B & C" in lines
    assert "TEL;TYPE=CELL:+4917012345" in lines
    assert "ADR;TYPE=WORK:;;Hauptstr. 1;Berlin;;10115;Deutschland" in lines
    assert "NOTE:Zeile 1\\nZeile 2" in lines


def test_mecard():
    assert (
        qrdata.encode("mecard", {"first_name": "Erika", "last_name": "Mustermann", "phone": "030 123"})
        == "MECARD:N:Mustermann,Erika;TEL:030123;;"
    )


def test_wifi_escaping_and_open_network():
    assert (
        qrdata.encode("wifi", {"ssid": 'My;Net"', "password": "pa:ss,word", "security": "WPA", "hidden": "1"})
        == 'WIFI:T:WPA;S:My\\;Net\\";P:pa\\:ss\\,word;H:true;;'
    )
    assert qrdata.encode("wifi", {"ssid": "Gast", "security": "nopass"}) == "WIFI:T:nopass;S:Gast;;"
    assert qrdata.validate("wifi", {"ssid": "x", "password": "short"}) is not None


def test_email_and_whatsapp_url_encoding():
    assert (
        qrdata.encode("email", {"address": "a@b.de", "subject": "Hallo Welt", "body": "1 & 2"})
        == "mailto:a@b.de?subject=Hallo%20Welt&body=1%20%26%202"
    )
    assert qrdata.encode("whatsapp", {"number": "0049 170 12", "message": "Hi du"}) == "https://wa.me/4917012?text=Hi%20du"
    assert qrdata.validate("whatsapp", {"number": "0170 123456"}) is not None


def test_geo_accepts_comma_decimals():
    assert qrdata.encode("geo", {"lat": "52,5", "lon": "13.404954"}) == "geo:52.5,13.404954"
    assert qrdata.validate("geo", {"lat": "100", "lon": "0"}) is not None


def test_event():
    ev = qrdata.encode("event", {"summary": "Grillen; Party", "start": "2026-10-07T18:00", "end": "2026-10-07T22:30"})
    assert ev.split("\r\n") == [
        "BEGIN:VEVENT", "SUMMARY:Grillen\\; Party", "DTSTART:20261007T180000", "DTEND:20261007T223000", "END:VEVENT",
    ]
    assert qrdata.validate("event", {"summary": "x", "start": "2026-10-07T18:00", "end": "2026-10-07T17:00"})


def test_girocode_epc_format():
    code = qrdata.encode(
        "girocode",
        {"name": "Erika Mustermann", "iban": "de89 3704 0044 0532 0130 00", "bic": "cobadeffxxx",
         "amount": "1.234,50", "reference": "Rechnung 42"},
    )
    assert code.split("\n") == [
        "BCD", "002", "1", "SCT", "COBADEFFXXX", "Erika Mustermann", "DE89370400440532013000",
        "EUR1234.50", "", "", "Rechnung 42",
    ]


@pytest.mark.parametrize("iban, ok", [
    ("DE89 3704 0044 0532 0130 00", True),
    ("DE89 3704 0044 0532 0130 01", False),
    ("AT61 1904 3002 3457 3201", True),
    ("XX00", False),
])
def test_iban_check(iban, ok):
    assert qrdata.iban_valid(iban) is ok


def test_qr_element_roundtrip_drops_foreign_fields():
    el = QrElement(content_type="wifi", values={"ssid": "Heim", "password": "geheim123", "text": "x", "iban": "DE"})
    data = json.loads(json.dumps(el.to_dict()))
    assert data["values"] == {"ssid": "Heim", "password": "geheim123"}
    again = element_from_dict(data)
    assert again.payload() == "WIFI:T:WPA;S:Heim;P:geheim123;;"


def test_old_templates_without_content_type_still_work():
    el = element_from_dict({"type": "qr", "x": 1, "y": 1, "width": 20, "height": 20, "data": "hallo"})
    assert el.content_type == "text" and el.payload() == "hallo"


def test_invalid_qr_renders_error_box_instead_of_crashing():
    label = Label(elements=[QrElement(content_type="girocode", values={"name": "X", "iban": "DE00"})])
    assert label.elements[0].validate()
    assert render(label).getbbox() is not None
