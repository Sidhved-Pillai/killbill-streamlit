from types import SimpleNamespace

import app


def test_model_fallbacks_include_stable_capacity_fallbacks():
    assert app.MODEL_FALLBACKS == [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]


def test_analyze_bills_uses_next_model_after_not_found(monkeypatch):
    requested_models = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            requested_models.append(model)
            if model == app.MODEL_FALLBACKS[0]:
                raise RuntimeError("404 NOT_FOUND: model is unavailable")
            return SimpleNamespace(
                text='[{"Invoice No.": "INV-1"}]',
                model_version=model,
                usage_metadata=None,
            )

    monkeypatch.setattr(app, "API_KEY", "test-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [{"ok": True}])
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    result = app.analyze_bills([SimpleNamespace(name="bill.jpeg")])

    assert result == [{"ok": True}]
    assert requested_models == app.MODEL_FALLBACKS[:2]


def test_retryable_errors_use_exponential_backoff_with_jitter(monkeypatch):
    attempts = []
    sleeps = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            attempts.append(model)
            if len(attempts) < app.MAX_RETRIES:
                raise RuntimeError("503 UNAVAILABLE: high demand")
            return SimpleNamespace(text="[]", model_version=model, usage_metadata=None)

    monkeypatch.setattr(app, "API_KEY", "test-key")
    monkeypatch.setattr(app.genai, "Client", lambda **kwargs: SimpleNamespace(models=FakeModels()))
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(app.random, "uniform", lambda start, end: 0.5)
    monkeypatch.setattr(app.time, "sleep", sleeps.append)

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == []
    assert attempts == [app.MODEL_FALLBACKS[0]] * app.MAX_RETRIES
    assert sleeps == [2.5]


def test_resilient_processing_splits_failed_batch_and_preserves_successes(monkeypatch):
    files = [SimpleNamespace(name=f"bill-{number}.jpeg") for number in range(3)]
    calls = []

    def fake_analyze(client, batch):
        calls.append([file.name for file in batch])
        if len(batch) > 1:
            raise RuntimeError("503 UNAVAILABLE")
        if batch[0].name == "bill-1.jpeg":
            raise RuntimeError("503 UNAVAILABLE")
        return [{"Invoice No.": batch[0].name}]

    monkeypatch.setattr(app, "API_KEY", "test-key")
    monkeypatch.setattr(app.genai, "Client", lambda **kwargs: object())
    monkeypatch.setattr(app, "_analyze_bill_batch", fake_analyze)
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    records, processed, failed = app.analyze_bills_resilient(files)

    assert calls == [[file.name for file in files], ["bill-0.jpeg"], ["bill-1.jpeg"], ["bill-2.jpeg"]]
    assert [record["Invoice No."] for record in records] == ["bill-0.jpeg", "bill-2.jpeg"]
    assert [file.name for file in processed] == ["bill-0.jpeg", "bill-2.jpeg"]
    assert [file.name for file, _ in failed] == ["bill-1.jpeg"]


def test_retryable_error_is_not_hidden_by_later_model_404(monkeypatch):
    class FakeModels:
        def generate_content(self, *, model, contents, config):
            if model == app.MODEL_FALLBACKS[0]:
                raise RuntimeError("503 UNAVAILABLE: high demand")
            raise RuntimeError("404 NOT_FOUND: unavailable")

    monkeypatch.setattr(app, "MAX_RETRIES", 1)
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    client = SimpleNamespace(models=FakeModels())
    try:
        app._analyze_bill_batch(client, [SimpleNamespace(name="bill.jpeg")])
    except RuntimeError as error:
        assert "503 UNAVAILABLE" in str(error)
    else:
        raise AssertionError("Expected the original retryable error")
