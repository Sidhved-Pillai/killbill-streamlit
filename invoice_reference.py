"""Invoice-specific billing values transcribed from the team's reference photo.

These are corrections for identified invoices, not a customer or route master.
Apply after master enrichment, before review/history; never on editor reruns.
"""

import csv
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
    """Override only legible reference fields for an exact invoice/date/origin."""
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
            result["Freight Charge"] = int(match["freight"])
            if match["short_address"]:
                result["To"] = match["short_address"]
            result["Lookup Status"] = (
                "✅ Invoice reference" if match["short_address"]
                else "⚠ Invoice freight reference; verify location"
            )
        enriched.append(result)
    return enriched
