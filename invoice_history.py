import os
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


DEFAULT_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "billing_history.db",
)
APP_TIMEZONE = ZoneInfo("Asia/Kolkata")

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


def _invoice_number_from_record(record):
    value = record.get("Invoice No.", record.get("Invoice No", ""))
    return str(value or "").strip()


def local_now():
    """Return the app's local wall-clock time for stable reporting boundaries."""
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def local_today():
    return local_now().date()


def find_processed_invoice_by_number(
    invoice_number,
    database_path=DEFAULT_DATABASE_PATH,
):
    """Return the most recent history event for an exact invoice number."""
    normalized_invoice_number = str(invoice_number or "").strip()
    if not normalized_invoice_number:
        return None

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                id,
                processed_timestamp,
                invoice_number,
                customer_name
            FROM processed_invoice_history
            WHERE invoice_number = ?
            ORDER BY processed_timestamp DESC, id DESC
            LIMIT 1
            """,
            (normalized_invoice_number,),
        ).fetchone()
    return dict(row) if row is not None else None


def _insert_processed_invoice(connection, record, processed_timestamp):
    values = (
        record.get("Date", ""),
        _invoice_number_from_record(record),
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


def store_processed_invoice(
    record,
    database_path=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    """Append one successfully processed invoice and return its history ID."""
    processed_timestamp = (processed_at or local_now()).isoformat(timespec="seconds")

    with sqlite3.connect(database_path) as connection:
        return _insert_processed_invoice(connection, record, processed_timestamp)


def store_processed_invoice_if_new(
    record,
    database_path=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    """Atomically append an invoice unless its invoice number is already stored.

    Returns ``(history_id, None)`` when inserted, or ``(None, existing_record)``
    when skipped. Records without an invoice number are stored normally because
    they cannot be identified as duplicates.
    """
    processed_timestamp = (processed_at or local_now()).isoformat(timespec="seconds")
    invoice_number = _invoice_number_from_record(record)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        existing = None
        if invoice_number:
            existing = connection.execute(
                """
                SELECT
                    id,
                    processed_timestamp,
                    invoice_number,
                    customer_name
                FROM processed_invoice_history
                WHERE invoice_number = ?
                ORDER BY processed_timestamp DESC, id DESC
                LIMIT 1
                """,
                (invoice_number,),
            ).fetchone()

        if existing is not None:
            return None, dict(existing)

        history_id = _insert_processed_invoice(connection, record, processed_timestamp)
        return history_id, None


def store_new_invoice_records(records, database_path=DEFAULT_DATABASE_PATH):
    """Store a batch and separate accepted records from skipped invoice numbers."""
    accepted_records = []
    duplicates_by_invoice = {}

    for record in records:
        history_id, existing = store_processed_invoice_if_new(record, database_path)
        invoice_number = _invoice_number_from_record(record)
        if history_id is None:
            duplicates_by_invoice.setdefault(
                invoice_number,
                {"record": record, "previous": existing},
            )
            continue
        accepted_records.append(record)

    return accepted_records, list(duplicates_by_invoice.values())


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


def count_processed_invoices(
    start_date,
    end_date,
    database_path=DEFAULT_DATABASE_PATH,
):
    """Count detailed history rows processed within an inclusive date range."""
    if start_date > end_date:
        return 0

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM processed_invoice_history
            WHERE processed_timestamp >= ?
              AND processed_timestamp < ?
            """,
            (
                datetime.combine(start_date, datetime.min.time()).isoformat(),
                datetime.combine(
                    end_date + timedelta(days=1),
                    datetime.min.time(),
                ).isoformat(),
            ),
        ).fetchone()
    return row[0]


def prune_processed_invoice_history(
    database_path=DEFAULT_DATABASE_PATH,
    today=None,
):
    """Remove reporting data from months before the current local month."""
    current_date = today or local_today()
    month_start = current_date.replace(day=1)
    cutoff = datetime.combine(month_start, datetime.min.time()).isoformat()

    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            """
            DELETE FROM processed_invoice_history
            WHERE processed_timestamp < ?
            """,
            (cutoff,),
        )
        removed_history_rows = cursor.rowcount

        has_dashboard_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'billing_history'
            """
        ).fetchone()
        removed_dashboard_rows = 0
        if has_dashboard_table is not None:
            cursor = connection.execute(
                """
                DELETE FROM billing_history
                WHERE processed_timestamp < ?
                """,
                (cutoff,),
            )
            removed_dashboard_rows = cursor.rowcount

    return removed_history_rows, removed_dashboard_rows


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
