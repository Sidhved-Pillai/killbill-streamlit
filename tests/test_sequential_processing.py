"""Regression coverage for resumable one-file-at-a-time processing."""

import app


class FakeUpload:
    def __init__(self, name, content):
        self.name = name
        self._content = content

    def getvalue(self):
        return self._content


class ProcessingProgress:
    def __init__(self, monkeypatch, fail_once=None, duplicate=None):
        self.calls = []
        self.attempts = {}
        self.fail_once = fail_once
        self.duplicate = duplicate

        def analyze(files):
            assert len(files) == 1
            name = files[0].name
            self.calls.append(name)
            self.attempts[name] = self.attempts.get(name, 0) + 1
            if name == self.fail_once and self.attempts[name] == 1:
                raise RuntimeError("temporary Gemini failure")
            return [{"Invoice No.": name, "Customer Name": name}]

        def store(records, database_path):
            record = records[0]
            if record["Invoice No."] == self.duplicate:
                return [], [{
                    "record": record,
                    "previous": {
                        "processed_timestamp": "2026-11-20T10:00:00",
                        "invoice_number": record["Invoice No."],
                    },
                }]
            return records, []

        monkeypatch.setattr(app, "analyze_bills", analyze)
        monkeypatch.setattr(app, "enrich_invoice_records", lambda records: records)
        monkeypatch.setattr(app, "store_new_invoice_records", store)
        monkeypatch.setattr(app, "store_processed_uploads", lambda *args: None)
        monkeypatch.setattr(app, "log_processed_invoice", lambda *args: None)


def uploads():
    return [
        FakeUpload("bill-1.jpg", b"one"),
        FakeUpload("bill-2.jpg", b"two"),
        FakeUpload("bill-3.jpg", b"three"),
    ]


def test_each_invoice_is_sent_in_its_own_request(monkeypatch):
    progress = ProcessingProgress(monkeypatch)
    files = uploads()
    state = app.create_processing_state(files)

    while state["status"] == "running":
        app.process_next_invoice(files, state)

    assert progress.calls == ["bill-1.jpg", "bill-2.jpg", "bill-3.jpg"]
    assert state["current_index"] == 3
    assert state["statuses"] == ["processed", "processed", "processed"]
    assert [record["Invoice No."] for record in state["records"]] == progress.calls


def test_two_invoice_window_keeps_requests_separate_and_persists_in_order(monkeypatch):
    progress = ProcessingProgress(monkeypatch)
    files = uploads()
    state = app.create_processing_state(files)

    app.process_invoice_window(files, state, worker_count=2)

    assert set(progress.calls) == {"bill-1.jpg", "bill-2.jpg"}
    assert state["statuses"] == ["processed", "processed", "pending"]
    assert state["current_index"] == 2
    assert [record["Invoice No."] for record in state["records"]] == [
        "bill-1.jpg", "bill-2.jpg"
    ]

    app.process_invoice_window(files, state, worker_count=2)
    assert state["status"] == "complete"
    assert state["statuses"] == ["processed", "processed", "processed"]


def test_failure_does_not_pause_later_bills_and_retry_only_retries_failure(monkeypatch):
    progress = ProcessingProgress(monkeypatch, fail_once="bill-2.jpg")
    files = uploads()
    state = app.create_processing_state(files)

    while state["status"] == "running":
        app.process_next_invoice(files, state)

    assert progress.calls == ["bill-1.jpg", "bill-2.jpg", "bill-3.jpg"]
    assert state["status"] == "complete"
    assert state["statuses"] == ["processed", "failed", "processed"]
    assert state["errors"]["1"]["filename"] == "bill-2.jpg"
    assert len(state["records"]) == 2

    app.retry_failed_invoices(state)
    while state["status"] == "running":
        app.process_next_invoice(files, state)

    assert progress.calls == [
        "bill-1.jpg", "bill-2.jpg", "bill-3.jpg", "bill-2.jpg"
    ]
    assert state["status"] == "complete"
    assert state["current_index"] == 3
    assert state["errors"] == {}


def test_multiple_failures_are_collected_without_manual_skips(monkeypatch):
    ProcessingProgress(monkeypatch, fail_once="bill-2.jpg")
    files = uploads()
    state = app.create_processing_state(files)
    while state["status"] == "running":
        app.process_next_invoice(files, state)

    assert state["statuses"] == ["processed", "failed", "processed"]
    assert state["current_index"] == 3
    assert state["status"] == "complete"
    assert [record["Invoice No."] for record in state["records"]] == [
        "bill-1.jpg", "bill-3.jpg"
    ]


def test_duplicate_is_collected_without_stopping_later_files(monkeypatch):
    progress = ProcessingProgress(monkeypatch, duplicate="bill-2.jpg")
    files = uploads()
    state = app.create_processing_state(files)

    while state["status"] == "running":
        app.process_next_invoice(files, state)

    assert progress.calls == ["bill-1.jpg", "bill-2.jpg", "bill-3.jpg"]
    assert state["statuses"] == ["processed", "duplicate", "processed"]
    assert len(state["duplicates"]) == 1
    assert state["duplicates"][0]["filename"] == "bill-2.jpg"
    assert [record["Invoice No."] for record in state["records"]] == [
        "bill-1.jpg", "bill-3.jpg"
    ]


def test_upload_signature_changes_when_order_or_content_changes():
    files = uploads()
    original = app.processing_batch_signature(files)
    assert app.processing_batch_signature(list(reversed(files))) != original
    assert app.processing_batch_signature([
        FakeUpload("bill-1.jpg", b"changed"), *files[1:]
    ]) != original


def test_failure_normalizes_non_string_filename(monkeypatch):
    file = FakeUpload(12345, b"invoice")
    monkeypatch.setattr(
        app,
        "analyze_bills",
        lambda files: (_ for _ in ()).throw(RuntimeError("temporary failure")),
    )
    state = app.create_processing_state([file])

    app.process_next_invoice([file], state)

    assert state["status"] == "complete"
    assert state["errors"]["0"]["filename"] == "12345"


def test_gemini_billing_failure_stops_once_without_skipping_invoice(monkeypatch):
    files = uploads()
    calls = []

    def billing_failure(selected_files):
        calls.append(selected_files[0].name)
        raise app.GeminiBillingError("credits depleted")

    monkeypatch.setattr(app, "analyze_bills", billing_failure)
    state = app.create_processing_state(files)

    app.process_next_invoice(files, state)

    assert calls == ["bill-1.jpg"]
    assert state["status"] == "service_error"
    assert state["current_index"] == 0
    assert state["statuses"] == ["pending", "pending", "pending"]
    assert state["errors"] == {}
