import os
import sys
import uuid
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from invoice_history import (  # noqa: E402
    _connection,
    _execute,
    count_processed_invoices,
    database_healthcheck,
    find_processed_invoice_by_number,
    init_invoice_history_database,
    search_processed_invoices,
    store_processed_invoice_if_new,
)


def main():
    database_url = os.environ["DATABASE_URL"]
    invoice_number = f"CODEX-HEALTHCHECK-{uuid.uuid4().hex}"
    processed_at = datetime(2026, 7, 28, 17, 45)

    init_invoice_history_database(database_url)
    assert database_healthcheck(database_url)

    try:
        history_id, existing = store_processed_invoice_if_new(
            {
                "Invoice No.": invoice_number,
                "Customer Name": "Hosted database health check",
                "Case": 1,
                "Jar": 0,
                "Freight Charge": 1,
            },
            database_url,
            processed_at=processed_at,
        )
        assert history_id is not None
        assert existing is None
        assert find_processed_invoice_by_number(invoice_number, database_url)["id"] == history_id
        assert len(search_processed_invoices(invoice_number, database_url)) == 1
        assert count_processed_invoices(
            date(2026, 7, 28),
            date(2026, 7, 28),
            database_url,
        ) >= 1

        duplicate_id, duplicate = store_processed_invoice_if_new(
            {"Invoice No.": invoice_number},
            database_url,
        )
        assert duplicate_id is None
        assert duplicate["id"] == history_id
    finally:
        with _connection(database_url) as connection:
            _execute(
                connection,
                "DELETE FROM processed_invoice_history WHERE invoice_number = %s",
                (invoice_number,),
            )

    print("Hosted database end-to-end verification passed.")


if __name__ == "__main__":
    main()
