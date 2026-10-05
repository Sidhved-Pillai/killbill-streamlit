import io
from datetime import date, datetime

import pandas as pd
import pytest
from openpyxl import load_workbook

from billing_statement import build_billing_statement, build_billing_statement_workbook
from freight_master import (
    apply_freight_lookup,
    apply_freight_rate_revision,
    apply_freight_rate_revision_to_dataframe,
)
from invoice_reference import apply_invoice_billing_reference


@pytest.mark.parametrize("base,revised", [
    (3844, 4644), (4509, 5309), (5073, 5873), (6509, 7309),
    (8748, 9548), (10160, 10960), (4327, 5127),
])
def test_all_approved_rates_change_at_september_boundary(base, revised):
    records = [{"Date": day, "Freight Charge": base} for day in
               ("31-Aug-26", "01-Sep-26", "05-Oct-26")]
    result = apply_freight_rate_revision(records)
    assert [r["Freight Charge"] for r in result] == [base, revised, revised]
    assert records[1]["Freight Charge"] == base
    assert apply_freight_rate_revision(result) == result


@pytest.mark.parametrize("invoice_date", [
    "01-Sep-26", "01-09-2026", "01/09/2026", "2026-09-01",
    date(2026, 9, 1), datetime(2026, 9, 1, 12, 30), pd.Timestamp("2026-09-01"),
])
def test_supported_invoice_date_formats(invoice_date):
    result = apply_freight_rate_revision([{"Date": invoice_date, "Freight Charge": 4509}])
    assert result[0]["Freight Charge"] == 5309


@pytest.mark.parametrize("invoice_date", [None, "", "invalid", "31-Sep-26", pd.NaT])
def test_unknown_invoice_date_does_not_guess_tariff(invoice_date):
    result = apply_freight_rate_revision([{"Date": invoice_date, "Freight Charge": 4509}])[0]
    assert result["Freight Charge"] == ""
    assert result["Lookup Status"] == "⚠ Verify invoice date for freight"


@pytest.mark.parametrize("charge", [0, "", None, 4902, 5127, 5309])
def test_zero_missing_special_and_already_updated_rates_remain_unchanged(charge):
    records = [{"Date": "01-Sep-26", "Freight Charge": charge}]
    assert apply_freight_rate_revision(records) == records


def test_rounded_master_rate_and_ton_rate_reach_statement_with_correct_months():
    records = [{
        "Date": day, "Invoice No.": number, "Customer Code": "MUMC001",
        "From": "Thane", "Vehicle No.": "TRUCK", "To": "Kalyan",
        "Case": 100, "Jar": 0,
    } for day, number in [
        ("31-Aug-26", "OLD"), ("01-Sep-26", "NEW"), ("01-Sep-26", "TON123"),
    ]]
    records = apply_freight_lookup(records, {"MUMC001": {"Thane": 4508.6394748902885}})
    records = apply_invoice_billing_reference(records)
    records = apply_freight_rate_revision(records)
    assert [r["Freight Charge"] for r in records] == [4509, 5309, 5127]
    summary = build_billing_statement(pd.DataFrame(records))
    workbook = load_workbook(io.BytesIO(build_billing_statement_workbook(summary)))
    assert workbook["Aug 2026"]["K4"].value == 4509
    assert workbook["Sep 2026"]["K4"].value == 5309
    assert workbook["Sep 2026"]["K5"].value == 5127
    assert workbook["Sep 2026"]["M24"].value == 10436


def test_confirmed_zero_and_numeric_invoice_references_remain_historical():
    records = [
        {"Invoice No.": "MUMCIN270053426", "Date": "23-Aug-26", "From": "Bhiwandi"},
        {"Invoice No.": "MUMCIN270049081", "Date": "07-Aug-26", "From": "Bhiwandi"},
        {"Invoice No.": "292264017722", "Date": "12-Aug-26", "From": "Bhiwandi"},
    ]
    result = apply_freight_rate_revision(apply_invoice_billing_reference(records))
    assert [r["Freight Charge"] for r in result] == [0, 0, 4327]


def test_persisted_review_dataframe_is_refreshed_idempotently():
    original = pd.DataFrame([
        {"Date": "05-Oct-26", "Invoice No.": "A", "Freight Charge": 3844},
        {"Date": "05-Oct-26", "Invoice No.": "B", "Freight Charge": 4327},
        {"Date": "31-Aug-26", "Invoice No.": "C", "Freight Charge": 4509},
        {"Date": "05-Oct-26", "Invoice No.": "D", "Freight Charge": 0},
    ], index=[4, 7, 9, 12])

    refreshed = apply_freight_rate_revision_to_dataframe(original)
    refreshed_again = apply_freight_rate_revision_to_dataframe(refreshed)

    assert refreshed["Freight Charge"].tolist() == [4644, 5127, 4509, 0]
    assert refreshed_again.equals(refreshed)
    assert refreshed.index.tolist() == [4, 7, 9, 12]
    assert original["Freight Charge"].tolist() == [3844, 4327, 4509, 0]


@pytest.mark.parametrize("dataframe", [None, pd.DataFrame()])
def test_empty_review_dataframe_refresh_is_safe(dataframe):
    result = apply_freight_rate_revision_to_dataframe(dataframe)
    if dataframe is None:
        assert result is None
    else:
        assert result.empty
