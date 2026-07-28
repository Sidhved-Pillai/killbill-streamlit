import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime

from invoice_history import (
    count_processed_invoices,
    find_processed_invoice_by_number,
    get_processed_invoice,
    init_invoice_history_database,
    prune_processed_invoice_history,
    search_processed_invoices,
    store_new_invoice_records,
    store_processed_invoice,
    store_processed_invoice_if_new,
)


class ProcessedInvoiceHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary_database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.database_path = temporary_database.name
        temporary_database.close()
        init_invoice_history_database(self.database_path)

    def tearDown(self):
        os.unlink(self.database_path)

    def test_stores_and_retrieves_complete_invoice(self):
        record = {
            "Date": "05-May-26",
            "Invoice No.": "MUMCIN270013536",
            "Vehicle No.": "MH04HD3996",
            "From": "Thane",
            "Customer Code": "MUMCO02703",
            "Customer Name": "SANTKRIPA DUGDHALAY(KALYAN-E)",
            "To": "Kalyan (East), Maharashtra",
            "Vehicle Type": "9MT",
            "Case": 550,
            "Jar": 0,
            "Freight Charge": 4508.64,
            "Lookup Status": "✅ Matched",
        }
        processed_at = datetime(2026, 7, 24, 22, 50)

        history_id = store_processed_invoice(
            record,
            self.database_path,
            processed_at=processed_at,
        )
        stored = get_processed_invoice(history_id, self.database_path)

        self.assertEqual(stored["processed_timestamp"], "2026-07-24T22:50:00")
        self.assertEqual(stored["invoice_date"], record["Date"])
        self.assertEqual(stored["invoice_number"], record["Invoice No."])
        self.assertEqual(stored["vehicle_number"], record["Vehicle No."])
        self.assertEqual(stored["origin"], record["From"])
        self.assertEqual(stored["customer_code"], record["Customer Code"])
        self.assertEqual(stored["customer_name"], record["Customer Name"])
        self.assertEqual(stored["destination"], record["To"])
        self.assertEqual(stored["vehicle_type"], record["Vehicle Type"])
        self.assertEqual(stored["cases"], record["Case"])
        self.assertEqual(stored["jars"], record["Jar"])
        self.assertEqual(stored["freight_charge"], record["Freight Charge"])
        self.assertEqual(stored["lookup_status"], record["Lookup Status"])

    def test_search_supports_partial_invoice_and_customer_matches(self):
        first = {
            "Invoice No.": "MUMCIN270013536",
            "Customer Name": "SANTKRIPA DUGDHALAY",
        }
        second = {
            "Invoice No.": "MUMCIN270099999",
            "Customer Name": "Another Customer",
        }
        store_processed_invoice(first, self.database_path)
        store_processed_invoice(second, self.database_path)

        invoice_matches = search_processed_invoices("2700135", self.database_path)
        customer_matches = search_processed_invoices("sAnTkRiPa", self.database_path)

        self.assertEqual([row["invoice_number"] for row in invoice_matches], [first["Invoice No."]])
        self.assertEqual([row["invoice_number"] for row in customer_matches], [first["Invoice No."]])

    def test_repeated_processing_creates_separate_history_entries(self):
        record = {
            "Invoice No.": "INV-001",
            "Customer Name": "Customer",
        }

        first_id = store_processed_invoice(record, self.database_path)
        second_id = store_processed_invoice(record, self.database_path)

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(search_processed_invoices("INV-001", self.database_path)), 2)

    def test_duplicate_check_uses_only_invoice_number_and_does_not_insert(self):
        original = {
            "Invoice No.": "INV-002",
            "Customer Name": "Original Customer",
            "Vehicle No.": "MH01AA0001",
        }
        duplicate = {
            "Invoice No.": "INV-002",
            "Customer Name": "Different Customer",
            "Vehicle No.": "MH02BB0002",
        }

        first_id, first_existing = store_processed_invoice_if_new(
            original,
            self.database_path,
        )
        duplicate_id, existing = store_processed_invoice_if_new(
            duplicate,
            self.database_path,
        )

        self.assertIsNotNone(first_id)
        self.assertIsNone(first_existing)
        self.assertIsNone(duplicate_id)
        self.assertEqual(existing["id"], first_id)
        self.assertEqual(existing["customer_name"], "Original Customer")
        self.assertEqual(len(search_processed_invoices("INV-002", self.database_path)), 1)

    def test_different_invoice_numbers_are_not_duplicates(self):
        first_id, _ = store_processed_invoice_if_new(
            {"Invoice No.": "INV-003", "Customer Name": "Same Customer"},
            self.database_path,
        )
        second_id, existing = store_processed_invoice_if_new(
            {"Invoice No.": "INV-004", "Customer Name": "Same Customer"},
            self.database_path,
        )

        self.assertNotEqual(first_id, second_id)
        self.assertIsNone(existing)

    def test_reupload_anyway_remains_an_explicit_append(self):
        record = {"Invoice No.": "INV-005", "Customer Name": "Customer"}
        first_id, _ = store_processed_invoice_if_new(record, self.database_path)
        skipped_id, _ = store_processed_invoice_if_new(record, self.database_path)
        reuploaded_id = store_processed_invoice(record, self.database_path)

        self.assertIsNone(skipped_id)
        self.assertNotEqual(first_id, reuploaded_id)
        self.assertEqual(len(search_processed_invoices("INV-005", self.database_path)), 2)

    def test_finds_most_recent_processing_for_duplicate_details(self):
        record = {"Invoice No.": "INV-006", "Customer Name": "Customer"}
        store_processed_invoice(
            record,
            self.database_path,
            processed_at=datetime(2026, 7, 20, 10, 0),
        )
        latest_id = store_processed_invoice(
            record,
            self.database_path,
            processed_at=datetime(2026, 7, 21, 11, 30),
        )

        existing = find_processed_invoice_by_number("INV-006", self.database_path)

        self.assertEqual(existing["id"], latest_id)
        self.assertEqual(existing["processed_timestamp"], "2026-07-21T11:30:00")

    def test_batch_returns_only_new_invoices_for_review(self):
        store_processed_invoice(
            {"Invoice No.": "EXISTING-001", "Customer Name": "Earlier Customer"},
            self.database_path,
            processed_at=datetime(2026, 7, 22, 9, 15),
        )
        records = [
            {"Invoice No.": "EXISTING-001", "Customer Name": "Uploaded Customer"},
            {"Invoice No.": "NEW-001", "Customer Name": "New Customer"},
        ]

        accepted, duplicates = store_new_invoice_records(records, self.database_path)

        self.assertEqual([row["Invoice No."] for row in accepted], ["NEW-001"])
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["record"]["Invoice No."], "EXISTING-001")
        self.assertEqual(
            duplicates[0]["previous"]["processed_timestamp"],
            "2026-07-22T09:15:00",
        )

    def test_batch_lists_a_repeated_invoice_only_once_in_duplicate_details(self):
        records = [
            {"Invoice No.": "NEW-002", "Case": 550},
            {"Invoice No.": "NEW-002", "Case": 96},
            {"Invoice No.": "NEW-002", "Case": 10},
        ]

        accepted, duplicates = store_new_invoice_records(records, self.database_path)

        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["Case"], 550)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["record"]["Invoice No."], "NEW-002")

    def test_counts_use_inclusive_calendar_date_boundaries(self):
        for invoice_number, processed_at in (
            ("BEFORE", datetime(2026, 6, 30, 23, 59, 59)),
            ("START", datetime(2026, 7, 1, 0, 0, 0)),
            ("MIDDLE", datetime(2026, 7, 15, 12, 30, 0)),
            ("END", datetime(2026, 7, 31, 23, 59, 59)),
            ("AFTER", datetime(2026, 8, 1, 0, 0, 0)),
        ):
            store_processed_invoice(
                {"Invoice No.": invoice_number},
                self.database_path,
                processed_at=processed_at,
            )

        count = count_processed_invoices(
            date(2026, 7, 1),
            date(2026, 7, 31),
            self.database_path,
        )

        self.assertEqual(count, 3)

    def test_invalid_count_range_returns_zero(self):
        self.assertEqual(
            count_processed_invoices(
                date(2026, 7, 2),
                date(2026, 7, 1),
                self.database_path,
            ),
            0,
        )

    def test_monthly_cleanup_removes_only_prior_months(self):
        for invoice_number, processed_at in (
            ("JUNE", datetime(2026, 6, 30, 23, 59, 59)),
            ("JULY-START", datetime(2026, 7, 1, 0, 0, 0)),
            ("JULY-LATEST", datetime(2026, 7, 28, 18, 0, 0)),
        ):
            store_processed_invoice(
                {"Invoice No.": invoice_number},
                self.database_path,
                processed_at=processed_at,
            )

        removed_history, removed_dashboard = prune_processed_invoice_history(
            self.database_path,
            today=date(2026, 7, 28),
        )

        self.assertEqual(removed_history, 1)
        self.assertEqual(removed_dashboard, 0)
        self.assertEqual(len(search_processed_invoices("", self.database_path)), 2)
        self.assertEqual(
            count_processed_invoices(
                date(2026, 7, 1),
                date(2026, 7, 31),
                self.database_path,
            ),
            2,
        )

    def test_monthly_cleanup_also_prunes_legacy_dashboard_rows(self):
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE billing_history (
                    id INTEGER PRIMARY KEY,
                    invoice_no TEXT NOT NULL,
                    processed_timestamp TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO billing_history (invoice_no, processed_timestamp)
                VALUES (?, ?)
                """,
                (
                    ("OLD", "2026-06-30T23:59:59"),
                    ("CURRENT", "2026-07-01T00:00:00"),
                ),
            )

        _, removed_dashboard = prune_processed_invoice_history(
            self.database_path,
            today=date(2026, 7, 28),
        )

        with sqlite3.connect(self.database_path) as connection:
            remaining = connection.execute(
                "SELECT invoice_no FROM billing_history"
            ).fetchall()
        self.assertEqual(removed_dashboard, 1)
        self.assertEqual(remaining, [("CURRENT",)])


if __name__ == "__main__":
    unittest.main()
