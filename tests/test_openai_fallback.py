"""Regression coverage for the Gemini-only processing policy."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import app


def _configure_gemini(monkeypatch, models):
    monkeypatch.setattr(app, "API_KEY", "google-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=models),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app, "log_gemini_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.st, "warning", lambda message: None)


def test_valid_gemini_result_is_returned(monkeypatch):
    class SuccessfulModels:
        def generate_content(self, **kwargs):
            assert kwargs["config"].response_mime_type == "application/json"
            return SimpleNamespace(
                text='[{"Invoice No.": "INV-GEMINI"}]',
                model_version="gemini-test",
                usage_metadata=None,
            )

    _configure_gemini(monkeypatch, SuccessfulModels())
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [{"provider": "gemini"}])

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "gemini"}
    ]


def test_all_gemini_models_failing_never_calls_openai(monkeypatch):
    requested_models = []

    class BusyModels:
        def generate_content(self, **kwargs):
            requested_models.append(kwargs["model"])
            raise RuntimeError("503 UNAVAILABLE")

    _configure_gemini(monkeypatch, BusyModels())
    monkeypatch.setattr(app, "MAX_RETRIES", 1)

    with pytest.raises(RuntimeError, match="available models"):
        app.analyze_bills([SimpleNamespace(name="bill.jpeg")])

    assert requested_models == app.MODEL_FALLBACKS


def test_zero_record_responses_end_with_gemini_error(monkeypatch):
    class EmptyModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="[]",
                model_version=kwargs["model"],
                usage_metadata=None,
            )

    _configure_gemini(monkeypatch, EmptyModels())
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [])

    with pytest.raises(RuntimeError, match="available models"):
        app.analyze_bills([SimpleNamespace(name="bill.jpeg")])


def test_gemini_deadline_returns_retry_message(monkeypatch):
    _configure_gemini(
        monkeypatch,
        SimpleNamespace(
            generate_content=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("Gemini must not start after the deadline")
            )
        ),
    )
    monkeypatch.setattr(app.time, "monotonic", iter([0.0, 61.0, 61.0]).__next__)

    with pytest.raises(RuntimeError, match="within 1 minute"):
        app.analyze_bills([SimpleNamespace(name="bill.jpeg")])


def test_project_has_no_openai_runtime_or_dependency():
    project_root = Path(__file__).parents[1]
    app_source = (project_root / "app.py").read_text()
    requirements = (project_root / "requirements.txt").read_text().lower().splitlines()

    assert "from openai import" not in app_source
    assert "OPENAI_API_KEY" not in app_source
    assert "analyze_bills_with_openai" not in app_source
    assert not any(line.strip().startswith("openai") for line in requirements)
