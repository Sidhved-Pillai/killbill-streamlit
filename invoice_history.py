import os
import sqlite3
from datetime import datetime


DEFAULT_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "billing_history.db",
)

HISTORY_COLUMNS = (
    "invoice_date",
    "invoice_number",
    "vehicle_number",
    "origin",
    "customer_code",
    "customer_name",
    "destination",
    "vehicle_type",
    "cases",
    "jars",
    "freight_charge",
    "lookup_status",
)


def init_invoice_history_database(database_path=DEFAULT_DATABASE_PATH):
    """Create the detailed, append-only processed invoice store."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_invoice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                processed_timestamp TEXT NOT NULL,
                invoice_date TEXT,
                invoice_number TEXT,
                vehicle_number TEXT,
                origin TEXT,
                customer_code TEXT,
                customer_name TEXT,
                destination TEXT,
                vehicle_type TEXT,
                cases NUMERIC,
                jars NUMERIC,
                freight_charge NUMERIC,
                lookup_status TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processed_invoice_number
            ON processed_invoice_history(invoice_number)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processed_customer_name
            ON processed_invoice_history(customer_name)
            """
        )


def _sqlite_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def store_processed_invoice(
    record,
    database_path=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    """Append one successfully processed invoice and return its history ID."""
    processed_timestamp = (processed_at or datetime.now()).isoformat(timespec="seconds")
    values = (
        record.get("Date", ""),
        record.get("Invoice No.", record.get("Invoice No", "")),
        record.get("Vehicle No.", record.get("Vehicle No", "")),
        record.get("From", ""),
        record.get("Customer Code", ""),
        record.get("Customer Name", ""),
        record.get("To", ""),
        record.get("Vehicle Type", ""),
        record.get("Case", ""),
        record.get("Jar", ""),
        record.get("Freight Charge", ""),
        record.get("Lookup Status", ""),
    )

    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO processed_invoice_history (
                processed_timestamp,
                invoice_date,
                invoice_number,
                vehicle_number,
                origin,
                customer_code,
                customer_name,
                destination,
                vehicle_type,
                cases,
                jars,
                freight_charge,
                lookup_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (processed_timestamp, *(_sqlite_value(value) for value in values)),
        )
        return cursor.lastrowid


def search_processed_invoices(query="", database_path=DEFAULT_DATABASE_PATH):
    """Return history summaries matching an invoice number or customer name."""
    search_term = f"%{str(query or '').strip()}%"
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                id,
                processed_timestamp,
                invoice_number,
                customer_name,
                freight_charge
            FROM processed_invoice_history
            WHERE invoice_number LIKE ? COLLATE NOCASE
               OR customer_name LIKE ? COLLATE NOCASE
            ORDER BY processed_timestamp DESC, id DESC
            """,
            (search_term, search_term),
        ).fetchall()
    return [dict(row) for row in rows]


def get_processed_invoice(history_id, database_path=DEFAULT_DATABASE_PATH):
    """Return all stored fields for one processing event."""
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                id,
                processed_timestamp,
                invoice_date,
                invoice_number,
                vehicle_number,
                origin,
                customer_code,
                customer_name,
                destination,
                vehicle_type,
                cases,
                jars,
                freight_charge,
                lookup_status
            FROM processed_invoice_history
            WHERE id = ?
            """,
            (history_id,),
        ).fetchone()
    return dict(row) if row is not None else None
