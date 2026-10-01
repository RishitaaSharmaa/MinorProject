"""Tests for JSON completion retries and the closed condition schema."""

import json
from types import SimpleNamespace

import groq
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.conditions import Condition
from llm.client import complete_json


class Payload(BaseModel):
    """Minimal test response schema."""

    model_config = ConfigDict(extra="forbid")
    value: int


def _response(content: str) -> SimpleNamespace:
    """Build a Groq-shaped response with token usage."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
    )


def test_json_client_retries_once_after_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Request JSON mode, retry malformed output once, then validate the result."""
    responses = iter([_response("not json"), _response(json.dumps({"value": 7}))])
    requests: list[dict[str, object]] = []

    class FakeGroq:
        """Capture requests and return queued responses."""

        def __init__(self, api_key: str) -> None:
            assert api_key == "test-key"
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs: object) -> SimpleNamespace:
            requests.append(kwargs)
            return next(responses)

    settings = SimpleNamespace(
        llm_provider="groq",
        llm_model="test-model",
        groq_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
    )
    monkeypatch.setattr("llm.client.get_settings", lambda: settings)
    monkeypatch.setattr(groq, "Groq", FakeGroq)

    result = complete_json("system", "user", Payload)

    assert result.value == 7
    assert len(requests) == 2
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "previous response" in requests[1]["messages"][0]["content"]


def test_json_client_stops_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not make more than two LLM attempts when schema validation fails."""
    requests: list[dict[str, object]] = []

    class FakeGroq:
        """Return an invalid payload every time."""

        def __init__(self, api_key: str) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs: object) -> SimpleNamespace:
            requests.append(kwargs)
            return _response("{}")

    settings = SimpleNamespace(
        llm_provider="groq",
        llm_model="test-model",
        groq_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
    )
    monkeypatch.setattr("llm.client.get_settings", lambda: settings)
    monkeypatch.setattr(groq, "Groq", FakeGroq)

    with pytest.raises(ValueError, match="did not match"):
        complete_json("system", "user", Payload)
    assert len(requests) == 2


def test_condition_schema_rejects_unknown_types_and_extra_fields() -> None:
    """Keep condition types, shape, and operators closed."""
    with pytest.raises(ValidationError):
        Condition(type="inventory_magic", entity_ref="item:SKU1", op="==", value=3)
    with pytest.raises(ValidationError):
        Condition(type="stock_lt", entity_ref="item:SKU1", op="<", value=3, invented=True)
    with pytest.raises(ValidationError):
        Condition(type="forecast_gte", entity_ref="item:SKU1", op=">", value=3)


def test_condition_schema_normalizes_common_supplier_risk_values() -> None:
    """Canonicalize supplier wording without expanding the condition types."""
    resolved = Condition(
        type="supplier_risk_resolved",
        entity_ref="supplier:SUP1",
        op="==",
        value="clear",
    )
    open_risk = Condition(
        type="supplier_risk_open",
        entity_ref="supplier:SUP1",
        op="==",
        value="strike",
    )
    closed_risk = Condition(
        type="supplier_risk_resolved",
        entity_ref="supplier:SUP1",
        op="==",
        value="closed",
    )

    assert resolved.value == "resolved"
    assert open_risk.value == "open"
    assert closed_risk.value == "resolved"