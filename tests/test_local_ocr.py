from local_ocr import _date, _invoice_number, _merge_pages


def test_normalizes_common_invoice_ocr_errors():
    assert _invoice_number("MUMCIN2T0G4007G") == "MUMCIN270040076"


def test_normalizes_invoice_date():
    assert _date("Invoice Date: 30-07-2026") == "30-Jul-26"


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
