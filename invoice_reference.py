"""Invoice-specific billing values transcribed from the team's reference photo.

These are corrections for identified invoices, not a customer or route master.
Apply after master enrichment, before review/history; never on editor reruns.
"""

import csv
import math
from datetime import datetime
from pathlib import Path

from freight_master import normalize_loading_point


REFERENCE_PATH = Path(__file__).parent / "data" / "invoice_billing_reference.csv"


def _invoice_key(value):
    return "".join(str(value or "").upper().split())


def _date_key(value):
    for date_format in ("%d-%b-%y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), date_format).date().isoformat()
        except ValueError:
            pass
    return None


def apply_invoice_billing_reference(records):
    """Fill master gaps for exact invoices, preserving confirmed zero exceptions."""
    with REFERENCE_PATH.open(newline="", encoding="utf-8") as reference_file:
        reference = {
            (row["invoice_number"], row["date"], row["origin"]): row
            for row in csv.DictReader(reference_file)
        }

    enriched = []
    for record in records:
        result = record.copy()
        key = (
            _invoice_key(record.get("Invoice No.", record.get("Invoice No", ""))),
            _date_key(record.get("Date")),
            normalize_loading_point(record.get("From")),
        )
        match = reference.get(key)
        if match:
            # The updated customer master supersedes the older photo, except
            # for the two explicitly confirmed invoice-specific free trips.
            confirmed_zero = int(match["freight"]) == 0
            try:
                has_freight = math.isfinite(float(result.get("Freight Charge")))
            except (TypeError, ValueError):
                has_freight = False
            use_freight = confirmed_zero or not has_freight
            use_location = confirmed_zero or result.get("Lookup Status") != "✅ Matched"
            if use_freight:
                result["Freight Charge"] = int(match["freight"])
            if use_location and match["short_address"]:
                result["To"] = match["short_address"]
            if use_freight or (use_location and match["short_address"]):
                result["Lookup Status"] = "✅ Invoice reference"
        enriched.append(result)
    return enriched
