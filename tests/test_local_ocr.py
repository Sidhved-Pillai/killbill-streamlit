from types import SimpleNamespace

from local_ocr import (
    INVOICE_RE,
    _date,
    _first_match,
    _invoice_number,
    _merge_pages,
    extract_invoices,
)


def test_normalizes_common_invoice_ocr_errors():
    assert _invoice_number("MUMCIN2T0G4007G") == "MUMCIN270040076"


def test_normalizes_invoice_date():
    assert _date("Invoice Date: 30-07-2026") == "30-Jul-26"


def test_matches_invoice_number_when_tesseract_inserts_spaces():
    lines = [{"text": "Invoice No: MUMCIN 270044985"}]
    assert _first_match(lines, INVOICE_RE, _invoice_number) == "MUMCIN270044985"


def test_rejects_truncated_invoice_number():
    lines = [{"text": "Invoice No: MUMCIN270037"}]
    assert _first_match(lines, INVOICE_RE, _invoice_number) == ""


def test_merges_pages_and_quantities():
    records = [
        {"Invoice No.": "INV1", "Date": "10-Jul-20", "Vehicle No.": "", "From": "Bhiwandi", "Loading Point": "Bhiwandi", "Customer Code": "C1", "Case": 0, "Jar": 0},
        {"Invoice No.": "INV1", "Date": "10-Jul-26", "Vehicle No.": "MH04HD4001", "From": "", "Loading Point": None, "Customer Code": "", "Case": 12, "Jar": 3},
        {"Invoice No.": "INV2", "Date": "11-Jul-26", "Vehicle No.": "V2", "From": "Bhiwandi", "Loading Point": "Bhiwandi", "Customer Code": "C2", "Case": 4, "Jar": 0},
    ]
    merged = _merge_pages(records)
    assert len(merged) == 2
    assert merged[0]["Date"] == "10-Jul-26"
    assert merged[0]["Vehicle No."] == "MH04HD4001"
    assert merged[0]["Case"] == 12
    assert merged[0]["Jar"] == 3


def test_does_not_mark_image_processed_when_invoice_number_is_unreadable(monkeypatch):
    uploaded = SimpleNamespace(name="faint.jpeg")
    monkeypatch.setattr(
        "local_ocr.extract_invoice",
        lambda file: {
            "Invoice No.": "", "Date": "", "Vehicle No.": "", "Customer Code": "",
            "From": "Bhiwandi", "Loading Point": "Bhiwandi", "Case": 0, "Jar": 0,
        },
    )

    records, processed, warnings, failed = extract_invoices([uploaded])

    assert records == []
    assert processed == []
    assert warnings == []
    assert failed[0][0] is uploaded
    assert "invoice number" in str(failed[0][1])
