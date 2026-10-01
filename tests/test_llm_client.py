"""Tests for provider routing through the centralized LLM wrapper."""

from types import SimpleNamespace

import groq
import pytest
from pydantic import SecretStr

from decisionwatch.config import Settings
from decisionwatch.llm.client import LLMClient


def test_tasks_use_configured_models_through_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route extraction and synthetic notes through the sole provider adapter."""
    settings = Settings(
        _env_file=None,
        groq_api_key=SecretStr("unit-test-key"),
        llm_provider="groq",
        llm_model="extract-model",
        note_llm_provider="groq",
        note_llm_model="notes-model",
    )
    captured: list[dict[str, object]] = []

    class FakeGroq:
        """Capture request data while matching the SDK response shape."""

        def __init__(self, api_key: str) -> None:
            assert api_key == "unit-test-key"
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs: object) -> SimpleNamespace:
            captured.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    monkeypatch.setattr("decisionwatch.llm.client.get_settings", lambda: settings)
    monkeypatch.setattr(groq, "Groq", FakeGroq)

    client = LLMClient()
    assert client.complete("extraction", "system", "note") == "ok"
    assert client.complete("synthetic_notes", "system", "note") == "ok"

    assert [request["model"] for request in captured] == ["extract-model", "notes-model"]