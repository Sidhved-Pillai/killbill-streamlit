from types import SimpleNamespace

import app


def test_model_fallbacks_include_stable_capacity_fallbacks():
    assert app.MODEL_FALLBACKS == [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
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


def test_retryable_errors_switch_models_without_sleeping(monkeypatch):
    attempts = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            attempts.append(model)
            if len(attempts) < len(app.MODEL_FALLBACKS):
                raise RuntimeError("503 UNAVAILABLE: high demand")
            return SimpleNamespace(text="[]", model_version=model, usage_metadata=None)

    monkeypatch.setattr(app, "API_KEY", "test-key")
    monkeypatch.setattr(app.genai, "Client", lambda **kwargs: SimpleNamespace(models=FakeModels()))
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == []
    assert attempts == app.MODEL_FALLBACKS


def test_resilient_processing_stops_after_outage_and_preserves_successes(monkeypatch):
    files = [SimpleNamespace(name=f"bill-{number}.jpeg") for number in range(6)]
    calls = []

    def fake_analyze(client, batch):
        calls.append([file.name for file in batch])
        if batch[0].name == "bill-4.jpeg":
            raise RuntimeError("503 UNAVAILABLE")
        return [{"Invoice No.": file.name} for file in batch]

    monkeypatch.setattr(app, "API_KEY", "test-key")
    monkeypatch.setattr(app.genai, "Client", lambda **kwargs: object())
    monkeypatch.setattr(app, "_analyze_bill_batch", fake_analyze)
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    records, processed, failed = app.analyze_bills_resilient(files)

    assert calls == [[file.name for file in files[:4]], [file.name for file in files[4:]]]
    assert [record["Invoice No."] for record in records] == [file.name for file in files[:4]]
    assert [file.name for file in processed] == [file.name for file in files[:4]]
    assert [file.name for file, _ in failed] == [file.name for file in files[4:]]


def test_retryable_error_is_not_hidden_by_later_model_404(monkeypatch):
    class FakeModels:
        def generate_content(self, *, model, contents, config):
            if model == app.MODEL_FALLBACKS[0]:
                raise RuntimeError("503 UNAVAILABLE: high demand")
            raise RuntimeError("404 NOT_FOUND: unavailable")

    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)

    client = SimpleNamespace(models=FakeModels())
    try:
        app._analyze_bill_batch(client, [SimpleNamespace(name="bill.jpeg")])
    except RuntimeError as error:
        assert "503 UNAVAILABLE" in str(error)
    else:
        raise AssertionError("Expected the original retryable error")


def test_client_disables_sdk_retries_and_sets_timeout(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(app.genai, "Client", fake_client)
    monkeypatch.setattr(app, "API_KEY", "test-key")

    app.build_genai_client()

    assert captured["api_key"] == "test-key"
    assert captured["http_options"].timeout == app.REQUEST_TIMEOUT_MS
    assert captured["http_options"].retry_options.attempts == 1
