import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse


DEFAULT_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "billing_history.db",
)
INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def _is_postgres(database_target):
    return str(database_target).startswith(("postgres://", "postgresql://"))


def _local_now():
    return datetime.now(INDIA_TIMEZONE).replace(tzinfo=None)


def local_today():
    return _local_now().date()


def _placeholder(database_target):
    return "%s" if _is_postgres(database_target) else "?"


@contextmanager
def _connection(database_target):
    if _is_postgres(database_target):
        import pg8000.dbapi

        parsed_url = urlparse(database_target)
        connection = pg8000.dbapi.connect(
            user=unquote(parsed_url.username or ""),
            password=unquote(parsed_url.password or ""),
            host=parsed_url.hostname,
            port=parsed_url.port or 5432,
            database=parsed_url.path.lstrip("/") or "postgres",
            timeout=10,
            # Supabase's pooler uses a project CA that isn't in the system
            # trust store. ``True`` requires encrypted TLS without disabling
            # SSL transport.
            ssl_context=True,
        )
    else:
        connection = sqlite3.connect(database_target)
        connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _execute(connection, statement, parameters=()):
    if isinstance(connection, sqlite3.Connection):
        return connection.execute(statement, parameters)
    cursor = connection.cursor()
    cursor.execute(statement, parameters)
    return _DictionaryCursor(cursor)


class _DictionaryCursor:
    """Expose pg8000 result rows with the same mapping interface as SQLite."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def _as_dict(self, row):
        if row is None:
            return None
        columns = [column[0] for column in self._cursor.description]
        return dict(zip(columns, row))

    def fetchone(self):
        return self._as_dict(self._cursor.fetchone())

    def fetchall(self):
        return [self._as_dict(row) for row in self._cursor.fetchall()]


def init_invoice_history_database(database_target=DEFAULT_DATABASE_PATH):
    """Create the durable processed-invoice history schema."""
    id_definition = (
        "BIGSERIAL PRIMARY KEY"
        if _is_postgres(database_target)
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    timestamp_type = "TIMESTAMP NOT NULL" if _is_postgres(database_target) else "TEXT NOT NULL"

    with _connection(database_target) as connection:
        _execute(
            connection,
            f"""
            CREATE TABLE IF NOT EXISTS processed_invoice_history (
                id {id_definition},
                processed_timestamp {timestamp_type},
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
            """,
        )
        _execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS idx_processed_invoice_number
            ON processed_invoice_history(invoice_number)
            """,
        )
        _execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS idx_processed_customer_name
            ON processed_invoice_history(customer_name)
            """,
        )
        _execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS idx_processed_timestamp
            ON processed_invoice_history(processed_timestamp)
            """,
        )


def _database_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def _numeric_value(value):
    value = _database_value(value)
    return None if value in ("", None) else value


def _invoice_number_from_record(record):
    value = record.get("Invoice No.", record.get("Invoice No", ""))
    return str(value or "").strip()


def _row_to_dict(row):
    return dict(row) if row is not None else None


def find_processed_invoice_by_number(
    invoice_number,
    database_target=DEFAULT_DATABASE_PATH,
):
    normalized_invoice_number = str(invoice_number or "").strip()
    if not normalized_invoice_number:
        return None

    placeholder = _placeholder(database_target)
    with _connection(database_target) as connection:
        row = _execute(
            connection,
            f"""
            SELECT id, processed_timestamp, invoice_number, customer_name
            FROM processed_invoice_history
            WHERE invoice_number = {placeholder}
            ORDER BY processed_timestamp DESC, id DESC
            LIMIT 1
            """,
            (normalized_invoice_number,),
        ).fetchone()
    return _row_to_dict(row)


def _insert_processed_invoice(
    connection,
    database_target,
    record,
    processed_timestamp,
):
    stored_timestamp = (
        processed_timestamp
        if _is_postgres(database_target)
        else processed_timestamp.isoformat(timespec="seconds")
    )
    values = (
        stored_timestamp,
        record.get("Date", ""),
        _invoice_number_from_record(record),
        record.get("Vehicle No.", record.get("Vehicle No", "")),
        record.get("From", ""),
        record.get("Customer Code", ""),
        record.get("Customer Name", ""),
        record.get("To", ""),
        record.get("Vehicle Type", ""),
        _numeric_value(record.get("Case", "")),
        _numeric_value(record.get("Jar", "")),
        _numeric_value(record.get("Freight Charge", "")),
        record.get("Lookup Status", ""),
    )
    placeholders = ", ".join([_placeholder(database_target)] * len(values))
    returning = " RETURNING id" if _is_postgres(database_target) else ""
    cursor = _execute(
        connection,
        f"""
        INSERT INTO processed_invoice_history (
            processed_timestamp, invoice_date, invoice_number, vehicle_number,
            origin, customer_code, customer_name, destination, vehicle_type,
            cases, jars, freight_charge, lookup_status
        )
        VALUES ({placeholders}){returning}
        """,
        tuple(_database_value(value) for value in values),
    )
    return cursor.fetchone()["id"] if _is_postgres(database_target) else cursor.lastrowid


def store_processed_invoice(
    record,
    database_target=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    processed_timestamp = processed_at or _local_now()
    with _connection(database_target) as connection:
        return _insert_processed_invoice(
            connection,
            database_target,
            record,
            processed_timestamp,
        )


def store_processed_invoice_if_new(
    record,
    database_target=DEFAULT_DATABASE_PATH,
    processed_at=None,
):
    processed_timestamp = processed_at or _local_now()
    invoice_number = _invoice_number_from_record(record)
    placeholder = _placeholder(database_target)

    with _connection(database_target) as connection:
        if not _is_postgres(database_target):
            _execute(connection, "BEGIN IMMEDIATE")
        elif invoice_number:
            _execute(
                connection,
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (invoice_number,),
            )
        existing = None
        if invoice_number:
            existing = _execute(
                connection,
                f"""
                SELECT id, processed_timestamp, invoice_number, customer_name
                FROM processed_invoice_history
                WHERE invoice_number = {placeholder}
                ORDER BY processed_timestamp DESC, id DESC
                LIMIT 1
                """,
                (invoice_number,),
            ).fetchone()

        if existing is not None:
            return None, _row_to_dict(existing)

        history_id = _insert_processed_invoice(
            connection,
            database_target,
            record,
            processed_timestamp,
        )
        return history_id, None


def store_new_invoice_records(records, database_target=DEFAULT_DATABASE_PATH):
    accepted_records = []
    duplicates_by_invoice = {}

    for record in records:
        history_id, existing = store_processed_invoice_if_new(record, database_target)
        invoice_number = _invoice_number_from_record(record)
        if history_id is None:
            duplicates_by_invoice.setdefault(
                invoice_number,
                {"record": record, "previous": existing},
            )
            continue
        accepted_records.append(record)

    return accepted_records, list(duplicates_by_invoice.values())


def search_processed_invoices(query="", database_target=DEFAULT_DATABASE_PATH):
    search_term = f"%{str(query or '').strip()}%"
    placeholder = _placeholder(database_target)
    comparison = "ILIKE" if _is_postgres(database_target) else "LIKE"
    with _connection(database_target) as connection:
        rows = _execute(
            connection,
            f"""
            SELECT id, processed_timestamp, invoice_number, customer_name, freight_charge
            FROM processed_invoice_history
            WHERE invoice_number {comparison} {placeholder}
               OR customer_name {comparison} {placeholder}
            ORDER BY processed_timestamp DESC, id DESC
            """,
            (search_term, search_term),
        ).fetchall()
    return [dict(row) for row in rows]


def get_processed_invoice(history_id, database_target=DEFAULT_DATABASE_PATH):
    placeholder = _placeholder(database_target)
    with _connection(database_target) as connection:
        row = _execute(
            connection,
            f"""
            SELECT
                id, processed_timestamp, invoice_date, invoice_number,
                vehicle_number, origin, customer_code, customer_name,
                destination, vehicle_type, cases, jars, freight_charge,
                lookup_status
            FROM processed_invoice_history
            WHERE id = {placeholder}
            """,
            (history_id,),
        ).fetchone()
    return _row_to_dict(row)


def count_processed_invoices(
    start_date,
    end_date,
    database_target=DEFAULT_DATABASE_PATH,
):
    if start_date > end_date:
        return 0

    placeholder = _placeholder(database_target)
    range_start = datetime.combine(start_date, datetime.min.time())
    range_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    with _connection(database_target) as connection:
        row = _execute(
            connection,
            f"""
            SELECT COUNT(*) AS invoice_count
            FROM processed_invoice_history
            WHERE processed_timestamp >= {placeholder}
              AND processed_timestamp < {placeholder}
            """,
            (range_start, range_end),
        ).fetchone()
    return row["invoice_count"]


def prune_previous_months(database_target=DEFAULT_DATABASE_PATH, today=None):
    current_date = today or local_today()
    month_start = datetime.combine(current_date.replace(day=1), datetime.min.time())
    placeholder = _placeholder(database_target)
    with _connection(database_target) as connection:
        cursor = _execute(
            connection,
            f"""
            DELETE FROM processed_invoice_history
            WHERE processed_timestamp < {placeholder}
            """,
            (month_start,),
        )
    return cursor.rowcount


def database_healthcheck(database_target=DEFAULT_DATABASE_PATH):
    with _connection(database_target) as connection:
        row = _execute(connection, "SELECT 1 AS healthy").fetchone()
    return row["healthy"] == 1
