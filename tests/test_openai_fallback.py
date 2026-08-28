from types import SimpleNamespace

import app


def test_valid_gemini_result_never_calls_openai(monkeypatch):
    class SuccessfulModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text='[{"Invoice No.": "INV-GEMINI"}]',
                model_version="gemini-test",
                usage_metadata=None,
            )

    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=SuccessfulModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [{"provider": "gemini"}])
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: (_ for _ in ()).throw(AssertionError("OpenAI must not run")),
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "gemini"}
    ]


def test_openai_runs_only_after_all_gemini_models_fail(monkeypatch):
    requested_models = []

    class BusyModels:
        def generate_content(self, **kwargs):
            requested_models.append(kwargs["model"])
            raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(app, "MAX_RETRIES", 1)
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=BusyModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    result = app.analyze_bills([SimpleNamespace(name="bill.jpeg")])

    assert result == [{"provider": "openai"}]
    assert requested_models == app.MODEL_FALLBACKS


def test_zero_record_gemini_responses_eventually_use_openai(monkeypatch):
    class EmptyModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="[]",
                model_version=kwargs["model"],
                usage_metadata=None,
            )

    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=EmptyModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "openai"}
    ]


def test_openai_schema_has_required_object_root():
    assert app.OPENAI_RESPONSE_SCHEMA["type"] == "object"
    assert "records" in app.OPENAI_RESPONSE_SCHEMA["properties"]


def test_one_minute_gemini_deadline_switches_to_openai(monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(app.time, "monotonic", iter([0.0, 61.0, 61.0]).__next__)
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **call_kwargs: (_ for _ in ()).throw(
                    AssertionError("Gemini must not start after the deadline")
                )
            )
        ),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "openai"}
    ]
