from types import SimpleNamespace

import numpy as np

from local_ocr import extract_invoices, merge_invoice_pages, parse_ocr_result


def _box(x, y, width=40, height=12):
    return np.array([[x, y], [x + width, y], [x + width, y + height], [x, y + height]])


def test_parses_positioned_bisleri_invoice_fields_and_jar_quantity():
    texts = (
        "Invoice No : MUMCIN270044986",
        "Vehicle No. : MH04HD4001",
        "Customer Code : MUMC018356",
        "Shipped From:",
        "RK LOGI WORLD COMPOUND WAREHOUSE NO F1 VILLAGE YEWAI BHIWANDI",
        "Product Description",
        "Qty",
        "Bisleri Water 20LTR 01 (MRP 100)",
        "200.00",
        "TOTAL",
    )
    boxes = (
        _box(500, 70), _box(500, 120), _box(360, 260), _box(700, 260),
        _box(700, 290), _box(250, 430), _box(680, 430), _box(220, 470),
        _box(670, 470), _box(100, 520),
    )

    record, missing = parse_ocr_result(
        texts,
        boxes,
        (960, 1280),
        ("Invoice Date : 30-07-2026",),
    )

    assert record["Date"] == "30-Jul-26"
    assert record["Invoice No."] == "MUMCIN270044986"
    assert record["Vehicle No."] == "MH04HD4001"
    assert record["Customer Code"] == "MUMC018356"
    assert record["Loading Point"] == "Bhiwandi"
    assert record["Case"] == 0
    assert record["Jar"] == 200
    assert missing == []


def test_reports_fields_that_need_manual_review():
    record, missing = parse_ocr_result(("Tax Invoice",), (_box(10, 10),), (960, 1280))

    assert record["Invoice No."] == ""
    assert "invoice number" in missing
    assert "item quantities" in missing


def test_merges_multi_page_invoice_and_corrects_outlier_year():
    records = [
        {"Invoice No.": "INV-1", "Date": "10-Jul-20", "Case": 0, "Jar": 0},
        {"Invoice No.": "INV-1", "Date": "10-Jul-26", "Case": 12, "Jar": 3},
        {"Invoice No.": "INV-2", "Date": "11-Jul-26", "Case": 4, "Jar": 0},
    ]

    merged = merge_invoice_pages(records)

    assert len(merged) == 2
    assert merged[0]["Date"] == "10-Jul-26"
    assert merged[0]["Case"] == 12
    assert merged[0]["Jar"] == 3


def test_uses_handwritten_case_stamp_when_table_is_too_faint():
    texts = ("Cases", "613")
    boxes = (_box(440, 1100), _box(250, 1120))

    record, missing = parse_ocr_result(
        texts,
        boxes,
        (960, 1280),
        ("Invoice Date: 10-07-2026",),
    )

    assert record["Case"] == 613
    assert "item quantities" not in missing


def test_preserves_underlying_ocr_initialization_error(monkeypatch):
    uploaded_file = SimpleNamespace(name="invoice.jpeg")
    expected_error = ImportError("libGL.so.1 is missing")
    monkeypatch.setattr("local_ocr.extract_invoice", lambda file: (_ for _ in ()).throw(expected_error))

    records, processed, warnings, failed = extract_invoices([uploaded_file])

    assert records == []
    assert processed == []
    assert warnings == []
    assert failed == [(uploaded_file, expected_error)]
