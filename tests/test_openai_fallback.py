import io
from types import SimpleNamespace

import app


def uploaded_image(name="bill.jpeg"):
    uploaded = io.BytesIO(b"fake-image-bytes")
    uploaded.name = name
    return uploaded


def test_openai_content_embeds_images_without_writing_files():
    content = app.build_openai_content([uploaded_image()])

    assert content[1] == {"type": "input_text", "text": "Document: bill.jpeg"}
    assert content[2]["type"] == "input_image"
    assert content[2]["image_url"].startswith("data:image/jpeg;base64,")
    assert content[2]["detail"] == "original"


def test_openai_object_wrapper_is_parsed_into_records():
    parsed = app.parse_gemini_response(
        '{"records":[{"Invoice No.":"INV-1","items":[]}]}'
    )

    assert len(parsed) == 1
    assert parsed[0]["Invoice No."] == "INV-1"


def test_analyze_bills_with_openai_uses_structured_responses(monkeypatch):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text='[{"Invoice No.": "INV-OPENAI"}]')

    monkeypatch.setattr(app, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        app,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(responses=FakeResponses()),
    )
    monkeypatch.setattr(app, "build_openai_content", lambda files: [])
    monkeypatch.setattr(app, "parse_gemini_response", lambda text: [{"ok": text}])

    result = app.analyze_bills_with_openai([SimpleNamespace(name="bill.jpeg")])

    assert result == [{"ok": '[{"Invoice No.": "INV-OPENAI"}]'}]
    assert captured["model"] == app.OPENAI_MODEL
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["schema"]["type"] == "object"
    assert "records" in captured["text"]["format"]["schema"]["properties"]
    assert captured["store"] is False


def test_google_busy_switches_to_openai_immediately(monkeypatch):
    class BusyModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("503 UNAVAILABLE: Google servers overloaded")

    monkeypatch.setattr(app, "API_KEY", "test-google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=BusyModels()),
    )
    monkeypatch.setattr(app, "build_batch_content_parts", lambda files: [])
    monkeypatch.setattr(app.st, "warning", lambda message: None)
    monkeypatch.setattr(
        app.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("must not retry Gemini")),
    )
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: [{"provider": "openai"}],
    )

    assert app.analyze_bills([SimpleNamespace(name="bill.jpeg")]) == [
        {"provider": "openai"}
    ]


def test_unavailable_gemini_model_switches_to_openai_immediately(monkeypatch):
    requested_models = []

    class MissingModels:
        def generate_content(self, **kwargs):
            requested_models.append(kwargs["model"])
            raise RuntimeError("404 NOT_FOUND: model unavailable")

    monkeypatch.setattr(app, "API_KEY", "test-google-key")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        app.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=MissingModels()),
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
    assert requested_models == [app.MODEL_FALLBACKS[0]]


def test_missing_google_key_does_not_automatically_use_openai(monkeypatch):
    monkeypatch.setattr(app, "API_KEY", "")
    monkeypatch.setattr(app, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        app,
        "analyze_bills_with_openai",
        lambda files: (_ for _ in ()).throw(AssertionError("must remain user-initiated")),
    )

    try:
        app.analyze_bills([SimpleNamespace(name="bill.jpeg")])
    except ValueError as error:
        assert "GOOGLE_API_KEY" in str(error)
    else:
        raise AssertionError("Missing Google configuration should fail the Gemini attempt")
