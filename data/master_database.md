# Customer and freight master

`master_database.xlsx` is the supplied `FRIEGHT M2.xlsx` received on
18 November 2026, copied without changing its contents. It replaces the
previous bundled workbook and contains 331 distinct MUMC customer codes.

The updated sheet uses two visual header rows: row 1 names each origin and row 2
labels KM, Slab, and Rate. Pandas retains row 2 as a non-customer row, which the
MUMC-code filter safely ignores. The loader still supports legacy layouts and
invalidates its cache when the workbook file changes.

Customers match by MUMC customer code. Short Address supplies the destination;
each origin's consecutive distance, slab, and rate columns supply freight.
Supported columns in this workbook are Thane, Vasai, Andheri, Vidya Vihar,
Bhiwandi, and Ambernath. Origins absent from the updated workbook do not inherit
obsolete rates from the previous workbook.

The workbook already contains the revised standard rates. The app converts those
standard values to their base tariff internally and applies the dated revision
below exactly once. This preserves correct processing for invoices before and
after 1 September 2026. Special values such as 3715, 4902, and 8454 remain as
supplied. A `0 / 0 / 0` route is a valid zero charge. Other mismatched slabs,
missing distances, and missing rates remain unresolved.

Numeric placeholder customer identifiers and warehouse descriptions are not
treated as MUMC codes. Six duplicated MUMC codes retain the existing first-row
precedence; no destinations or rates are merged across duplicate rows.

The updated master takes priority over the older invoice photo references.
Those references only fill unresolved fields on their exact invoices, except
the two intentional zero-charge invoices, which remain explicit exceptions.
The TON delivery-challan rate and invoice/history duplicate handling remain
unchanged. Previously saved history and downloaded workbooks are not rewritten.

## Freight revision effective 1 September 2026

The billing team confirmed the effective date shown in the October update's
screenshot is **1 September 2026**, based on the invoice date, not upload date.
After master/reference lookup and existing rounding, the app applies:

| Base freight | Revised freight |
| --- | --- |
| 3844 | 4644 |
| 4509 | 5309 |
| 5073 | 5873 |
| 6509 | 7309 |
| 8748 | 9548 |
| 10160 | 10960 |
| 4327 | 5127 |

This includes TON delivery challans and the capped top rate. Earlier invoice
dates retain their original rates. Zero charges, missing rates, and unrelated
special rates are unchanged. An invalid/missing invoice date leaves an affected
charge blank and flags it for review. The workbook retains base rates so older
invoices can still be processed accurately. Conversion occurs before history
storage and editing; editor reruns and exports never add the increase again.
Existing saved history/downloads are not retroactively repriced.
