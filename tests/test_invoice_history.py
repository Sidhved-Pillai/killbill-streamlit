import os
import tempfile
import unittest
from datetime import datetime

from invoice_history import (
    get_processed_invoice,
    init_invoice_history_database,
    search_processed_invoices,
    store_processed_invoice,
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


if __name__ == "__main__":
    unittest.main()
