from types import SimpleNamespace

import app


def test_model_fallbacks_include_stable_capacity_fallbacks():
    assert app.MODEL_FALLBACKS == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
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
    assert sleeps == [2.5, 4.5]
