# Customer and freight master

`master_database.xlsx` is the supplied `FRIEGHT M2-june New File 2026.xlsx`,
copied without changing its contents. It replaces the previous bundled workbook.
It contains 319 distinct MUMC customer codes, including 24 additional codes.

The updated sheet has headers in row 1. The loader also supports the legacy
row-2 layout and invalidates its cache when the workbook file changes.

Customers match by MUMC customer code. Short Address supplies the destination;
each origin's consecutive distance, slab, and rate columns supply freight.
Supported columns in this workbook are Kamshet, Thane, Vasai, Andheri,
Vidya Vihar, Bhiwandi, Ambernath, and Wada. Origins absent from the updated
workbook do not inherit obsolete rates from the previous workbook.

Existing standard-rate rounding remains unchanged: for example, distance 99,
slab 81-110, rate 8747.856159 becomes 8748. The billing team explicitly confirmed
that the top slab labelled 110-130 also applies above 130 km at the capped rate
of 10160. Other mismatched slabs, missing distances, and missing rates remain
unresolved. Numeric zero distances and zero rates are valid values.

Numeric placeholder customer identifiers and warehouse descriptions are not
treated as MUMC codes. Seven duplicated MUMC codes retain the existing first-row
precedence; no destinations or rates are merged across duplicate rows.

The updated master takes priority over the older invoice photo references.
Those references only fill unresolved fields on their exact invoices, except
the two intentional zero-charge invoices, which remain explicit exceptions.
The TON delivery-challan rate and invoice/history duplicate handling remain
unchanged. Previously saved history and downloaded workbooks are not rewritten.
