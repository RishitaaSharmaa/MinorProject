"""Tests for application settings safety constraints."""

import pytest
from pydantic import ValidationError

from decisionwatch.config import Settings


def test_extraction_and_note_models_must_differ() -> None:
    """Reject a configuration that reuses one provider/model pair."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            llm_provider="groq",
            llm_model="same-model",
            note_llm_provider="groq",
            note_llm_model="same-model",
        )


def test_distinct_models_are_accepted() -> None:
    """Allow separate models on one provider as required for dataset/evaluation."""
    settings = Settings(
        _env_file=None,
        llm_provider="groq",
        llm_model="extract-model",
        note_llm_provider="groq",
        note_llm_model="notes-model",
    )

    assert settings.llm_model != settings.note_llm_model