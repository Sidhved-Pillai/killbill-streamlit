"""Exercise the deployed workbook and both supported Excel layouts."""

import io
import os

import pandas as pd
import pytest
from openpyxl import load_workbook

import customer_master
from billing_statement import build_billing_statement, build_billing_statement_workbook
from customer_master import apply_customer_master_lookup, build_customer_lookup, read_customer_master
from freight_master import apply_freight_lookup, build_freight_lookup, normalize_loading_point
from invoice_reference import apply_invoice_billing_reference


@pytest.fixture(scope="module")
def master():
    return customer_master.load_customer_master()


def test_deployed_workbook_includes_updated_customer_codes(master):
    customers = build_customer_lookup(master)
    assert len(customers) == 319
    assert customers["MUMC021168"]["To"] == "Kalyan East"
    assert customers["MUMC021169"]["To"] == "Taloja"
    assert customers["MUMC021357"]["To"] == "BHIWANDI"
    assert customers["MUMC021572"]["To"] == "VASAI"
    assert "1" not in customers  # Placeholder identifiers are not customer codes.


@pytest.mark.parametrize("origin,expected", [
    ("Kamshet", 8748), ("Thane", 4509), ("Vasai", 6509),
    ("Andheri", 5073), ("Vidya Vihar", 5073),
    ("Bhiwandi", 3844), ("Ambernath", 3844), ("Wada", 6509),
])
def test_example_customer_uses_correct_distance_slab_rate_triplet(master, origin, expected):
    result = apply_freight_lookup([
        {"Customer Code": "MUMC002959", "Loading Point": origin}
    ], build_freight_lookup(master))[0]
    assert result["Freight Charge"] == expected


def test_distance_above_130_uses_confirmed_capped_rate(master):
    row = master.loc[master["Customer code"] == "MUMC002961"].iloc[0]
    assert float(row["Distance from Kamshet"]) == 185
    result = apply_freight_lookup([
        {"Customer Code": "MUMC002961", "From": "Kamshet"}
    ], build_freight_lookup(master))[0]
    assert result["Freight Charge"] == 10160


def test_updated_master_wins_over_photo_through_billing_export(master):
    records = [{
        "Customer Code": "MUMC021727", "Invoice No.": "MUMCIN270050289",
        "Date": "11-Aug-26", "From": "Thane", "Vehicle No.": "MH04HY7998",
        "Customer Name": "Extracted name", "To": "Long extracted address",
        "Case": 1150, "Jar": 0,
    }]
    records = apply_customer_master_lookup(records, build_customer_lookup(master))
    records = apply_freight_lookup(records, build_freight_lookup(master))
    records = apply_invoice_billing_reference(records)
    assert records[0]["To"] == "THAKURLI EAST"
    assert records[0]["Freight Charge"] == 4509  # Photo had 5073 / Ambernath.
    summary = build_billing_statement(pd.DataFrame(records))
    sheet = load_workbook(io.BytesIO(build_billing_statement_workbook(summary))).active
    assert sheet["G4"].value == "THAKURLI EAST"
    assert sheet["K4"].value == 4509


@pytest.mark.parametrize("header_row", [0, 1])
def test_loader_accepts_new_and_legacy_layouts(tmp_path, header_row):
    path = tmp_path / "master.xlsx"
    frame = pd.DataFrame({
        "Customer code": ["MUMC001"], "Name of the Distributor": ["Customer"],
        "Short Address": ["Locality"],
    })
    frame.to_excel(path, index=False, startrow=header_row)
    assert build_customer_lookup(read_customer_master(path))["MUMC001"]["To"] == "Locality"


def test_replacing_workbook_refreshes_cached_master(tmp_path, monkeypatch):
    path = tmp_path / "master.xlsx"
    frame = pd.DataFrame({
        "Customer code": ["MUMC001"], "Name of the Distributor": ["Customer"],
        "Short Address": ["Old"],
    })
    frame.to_excel(path, index=False)
    monkeypatch.setattr(customer_master, "MASTER_DATABASE_PATH", str(path))
    assert customer_master.load_customer_master().iloc[0]["Short Address"] == "Old"
    previous_ns = path.stat().st_mtime_ns
    frame["Short Address"] = "New"
    frame.to_excel(path, index=False)
    os.utime(path, ns=(previous_ns + 1000000000, previous_ns + 1000000000))
    assert customer_master.load_customer_master().iloc[0]["Short Address"] == "New"


@pytest.mark.parametrize("value", ["Ambernath", "AMBARNATH", "Ambernath Depot"])
def test_ambernath_origin_is_supported(value):
    assert normalize_loading_point(value) == "Ambernath"


@pytest.mark.parametrize("distance,slab,rate,expected", [
    (99, "81-110", 8747.856159, 8748),
    (185, "110-130", 10159.810450, 10160),
    (185, "81-110", 8747.856159, ""),
    (None, "110-130", 10160, ""),
    (185, "110-130", None, ""),
    (0, "0-20", 0, 0),
])
def test_top_cap_does_not_relax_other_invalid_or_missing_routes(distance, slab, rate, expected):
    frame = pd.DataFrame({
        "Customer code": ["MUMC001"], "Distance from Kamshet": [distance],
        "Slab": [slab], "Rate": [rate],
    })
    result = apply_freight_lookup([
        {"Customer Code": "MUMC001", "From": "Kamshet"}
    ], build_freight_lookup(frame))[0]
    assert result["Freight Charge"] == expected
